"""Persistencia PostgreSQL dos produtos raspados, com deduplicacao em lote.

Mantem o schema idempotente (cria colunas/indices que faltarem) e evita
N+1 queries: os links ja existentes sao carregados em uma unica consulta
antes do upsert do lote inteiro.
"""

from __future__ import annotations

import json
import logging
from typing import Iterable

import psycopg2
import psycopg2.extras

from configuracao import get_config
from normalizacao import inferir_categoria

logger = logging.getLogger(__name__)

TABELAS_PRODUTOS = ("produtos_kabum", "produtos_mercadolivre", "produtos_lojas")


def get_connection():
    config = get_config()
    return psycopg2.connect(
        host=config.pg_host,
        port=config.pg_port,
        user=config.pg_user,
        password=config.pg_password,
        dbname=config.pg_database,
    )


def preparar_schema() -> bool:
    """Garante colunas, extensoes e indices de busca/deduplicacao.

    Idempotente: pode ser chamada em toda execucao do scraper sem custo
    relevante (todas as operacoes usam IF NOT EXISTS / checagem previa).
    """
    connection = cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS produtos_lojas (
                id SERIAL PRIMARY KEY, nome TEXT NOT NULL,
                preco NUMERIC(12,2) NOT NULL CHECK (preco > 0),
                link TEXT NOT NULL UNIQUE, origem TEXT NOT NULL,
                imagem_url TEXT, imagens_urls TEXT, categoria TEXT,
                atualizado_em TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            )
        """)
        # unaccent() e STABLE, nao IMMUTABLE; um indice de expressao exige
        # IMMUTABLE, entao criamos um wrapper que fixa o dicionario.
        # unaccent() e chamada com o nome de esquema qualificado
        # (public.unaccent) porque, ao criar um indice de expressao, o
        # Postgres faz "inline expansion" do corpo desta funcao SQL e essa
        # expansao nao resolve nomes nao qualificados via search_path.
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION busca_unaccent(text)
            RETURNS text AS $$
                SELECT public.unaccent($1)
            $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
            """
        )

        for tabela in TABELAS_PRODUTOS:
            cursor.execute(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE table_schema = 'public' AND table_name = %s",
                (tabela,),
            )
            if not cursor.fetchone():
                continue

            cursor.execute(
                f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS imagens_urls TEXT"
            )
            cursor.execute(
                f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS categoria TEXT"
            )
            cursor.execute(
                f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS atualizado_em "
                "TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"
            )
            cursor.execute(f"SELECT id, nome FROM {tabela} WHERE categoria IS NULL")
            categorias = [(categoria, id_) for id_, nome in cursor.fetchall()
                          if (categoria := inferir_categoria(nome))]
            if categorias:
                psycopg2.extras.execute_batch(cursor,
                    f"UPDATE {tabela} SET categoria=%s WHERE id=%s AND categoria IS NULL", categorias)

            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = %s", (tabela,)
            )
            indices = {row[0] for row in cursor.fetchall()}

            if f"ux_{tabela}_link" not in indices:
                cursor.execute(
                    f"SELECT link FROM {tabela} GROUP BY link HAVING COUNT(*) > 1 LIMIT 1"
                )
                if cursor.fetchone():
                    logger.warning(
                        "%s possui links duplicados; indice unico nao aplicado", tabela
                    )
                else:
                    cursor.execute(
                        f"CREATE UNIQUE INDEX ux_{tabela}_link ON {tabela} (link)"
                    )

            # A tsvector antiga nao e usada pela API (que faz ILIKE), entao
            # e substituida por um indice trigram sobre o nome sem acento.
            tsvector_antigo = {
                "produtos_kabum": "idx_kabum_nome",
                "produtos_mercadolivre": "idx_mercadolivre_nome",
            }.get(tabela)
            if tsvector_antigo and tsvector_antigo in indices:
                cursor.execute(f"DROP INDEX IF EXISTS {tsvector_antigo}")

            trgm_index = f"idx_{tabela}_nome_trgm"
            if trgm_index not in indices:
                cursor.execute(
                    f"CREATE INDEX {trgm_index} ON {tabela} "
                    f"USING gin (busca_unaccent(lower(nome)) gin_trgm_ops)"
                )

            if f"idx_{tabela}_categoria" not in indices:
                cursor.execute(
                    f"CREATE INDEX idx_{tabela}_categoria ON {tabela} (categoria)"
                )

        connection.commit()
        return True
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Falha ao preparar schema de produtos")
        return False
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def _links_existentes(cursor, tabela: str, links: list[str]) -> set[str]:
    if not links:
        return set()
    existentes: set[str] = set()
    for inicio in range(0, len(links), 500):
        lote = links[inicio : inicio + 500]
        cursor.execute(
            f"SELECT link FROM {tabela} WHERE link = ANY(%s)", (lote,)
        )
        existentes.update(row[0] for row in cursor.fetchall())
    return existentes


_UPSERT_KABUM_SQL = """
    INSERT INTO produtos_kabum (nome, preco, link, imagem_url, imagens_urls, categoria, atualizado_em)
    VALUES (%s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (link) DO UPDATE SET
        nome = EXCLUDED.nome,
        preco = EXCLUDED.preco,
        imagem_url = EXCLUDED.imagem_url,
        imagens_urls = EXCLUDED.imagens_urls,
        categoria = EXCLUDED.categoria,
        atualizado_em = NOW()
"""


def salvar_produtos_kabum(produtos: Iterable[dict]) -> tuple[int, int]:
    """Upsert em lote. Retorna (inseridos_ou_atualizados, ignorados_invalidos)."""
    itens = [item for item in produtos if item.get("nome") and item.get("link")]
    ignorados = 0
    if not itens:
        return 0, ignorados

    vistos: dict[str, dict] = {}
    for item in itens:
        if item["link"] in vistos:
            ignorados += 1
        vistos[item["link"]] = item
    itens = list(vistos.values())

    connection = cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        linhas = [
            (
                item["nome"],
                item["preco"],
                item["link"],
                item.get("imagem_url"),
                json.dumps(item["imagens_urls"], ensure_ascii=False) if item.get("imagens_urls") else None,
                item.get("categoria"),
            )
            for item in itens
        ]
        psycopg2.extras.execute_batch(cursor, _UPSERT_KABUM_SQL, linhas, page_size=100)
        connection.commit()
        logger.info("Upsert de %s produtos Kabum concluido", len(linhas))
        return len(linhas), ignorados
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Lote de produtos Kabum revertido")
        return 0, len(itens)
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def buscar_links_existentes(links: Iterable[str], tabela: str = "produtos_kabum") -> set[str]:
    """Consulta em uma unica query quais links ja estao no banco.

    Usado para pular a coleta de detalhes (e imagens) de produtos ja
    conhecidos, evitando requisicoes desnecessarias.
    """
    normalizados = list(dict.fromkeys(str(link).strip() for link in links if link))
    if not normalizados:
        return set()
    connection = cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        return _links_existentes(cursor, tabela, normalizados)
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def salvar_produtos_lojas(produtos: Iterable[dict]) -> tuple[int, int]:
    """Atualiza preco e fotos das novas lojas, deduplicando pelo link."""
    recebidos = list(produtos)
    itens = {item["link"]: item for item in recebidos
             if item.get("nome") and item.get("link") and item.get("origem")
             and item.get("preco") is not None and item["preco"] > 0}
    if not itens:
        return 0, len(recebidos)
    connection = cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        linhas = [(item["nome"], item["preco"], item["link"], item["origem"],
                   item.get("imagem_url"), json.dumps(item.get("imagens_urls", [])),
                   item.get("categoria")) for item in itens.values()]
        psycopg2.extras.execute_batch(cursor, """
            INSERT INTO produtos_lojas
                (nome, preco, link, origem, imagem_url, imagens_urls, categoria)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (link) DO UPDATE SET
                nome = EXCLUDED.nome, preco = EXCLUDED.preco, origem = EXCLUDED.origem,
                imagem_url = COALESCE(EXCLUDED.imagem_url, produtos_lojas.imagem_url),
                imagens_urls = CASE WHEN EXCLUDED.imagem_url IS NOT NULL
                    THEN EXCLUDED.imagens_urls ELSE produtos_lojas.imagens_urls END,
                categoria = COALESCE(EXCLUDED.categoria, produtos_lojas.categoria),
                atualizado_em = NOW()
        """, linhas, page_size=100)
        connection.commit()
        return len(itens), len(recebidos) - len(itens)
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Falha ao salvar produtos das novas lojas")
        return 0, len(recebidos)
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
