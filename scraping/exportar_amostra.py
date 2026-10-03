"""Exporta ate 10 produtos por loja, sem usuarios ou credenciais."""
from pathlib import Path
import json
import re
from urllib.parse import urlsplit, urlunsplit

from configuracao import BACKEND_DIR, get_config
import psycopg2


def foto_valida(url):
    return isinstance(url, str) and url.startswith(("http://", "https://")) and not any(
        sinal in url.lower() for sinal in ("/icons/", ".svg", "placeholder", "spacer", "transparent"))


def ler_dump():
    texto = (BACKEND_DIR / "database_dump.sql").read_text(encoding="utf-8")
    resultado = {}
    for tabela in ("produtos_kabum", "produtos_mercadolivre", "produtos_lojas"):
        bloco = re.search(r"COPY public\." + tabela + r" \((.*?)\) FROM stdin;\n(.*?)\n\\\.", texto, re.S)
        registros = []
        if bloco:
            colunas = bloco[1].split(", ")
            for linha in bloco[2].splitlines():
                valores = [None if valor == r"\N" else valor.replace(r"\t", "\t").replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\\", "\\")
                           for valor in linha.split("\t")]
                registros.append(dict(zip(colunas, valores)))
        resultado[tabela] = registros
    return resultado


def ler_banco():
    config = get_config()
    with psycopg2.connect(host=config.pg_host, port=config.pg_port, user=config.pg_user,
                          password=config.pg_password, dbname=config.pg_database, connect_timeout=3) as conn:
        resultado = {}
        with conn.cursor() as cursor:
            for tabela in ("produtos_kabum", "produtos_mercadolivre", "produtos_lojas"):
                cursor.execute("SELECT to_regclass(%s)", ("public." + tabela,))
                if cursor.fetchone()[0] is None:
                    resultado[tabela] = []
                    continue
                cursor.execute(f"SELECT * FROM {tabela} ORDER BY id LIMIT 500")
                colunas = [coluna.name for coluna in cursor.description]
                resultado[tabela] = [dict(zip(colunas, linha)) for linha in cursor.fetchall()]
        return resultado


def literal(valor):
    return "NULL" if valor is None else "'" + str(valor).replace("'", "''") + "'"


def main():
    fonte = "PostgreSQL local"
    try:
        dados = ler_banco()
    except psycopg2.Error:
        fonte = "database_dump.sql local (banco indisponivel)"
        dados = ler_dump()
    sql = ["-- Amostra publica: apenas produtos e URLs de fotos; sem dados pessoais.",
           "-- Fonte: " + fonte, "-- Execute database_setup.sql antes deste arquivo.",
           "BEGIN;", "SET standard_conforming_strings = on;"]
    contagens = {}
    for tabela, registros in dados.items():
        contagens[tabela] = 0
        vistos = set()
        por_origem = {}
        for item in registros:
            imagem = item.get("imagem_url")
            if not foto_valida(imagem):
                continue
            partes = urlsplit(item.get("link") or "")
            if not partes.hostname or partes.hostname.startswith("click"):
                continue
            link = urlunsplit((partes.scheme, partes.netloc, partes.path, "", ""))
            origem = item.get("origem", tabela)
            if link in vistos or por_origem.get(origem, 0) >= 10:
                continue
            vistos.add(link)
            por_origem[origem] = por_origem.get(origem, 0) + 1
            colunas = ["nome", "preco", "link", "imagem_url", "categoria"]
            valores = [item["nome"], item["preco"], link, imagem, item.get("categoria")]
            if tabela != "produtos_mercadolivre":
                try:
                    fotos = json.loads(item.get("imagens_urls") or "[]")
                except (TypeError, ValueError):
                    fotos = []
                fotos = [foto for foto in fotos if foto_valida(foto)] if isinstance(fotos, list) else []
                colunas.append("imagens_urls")
                valores.append(json.dumps(fotos or [imagem], ensure_ascii=False))
            if tabela == "produtos_lojas":
                colunas.append("origem")
                valores.append(item["origem"])
            sql.append(f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join(literal(v) for v in valores)}) ON CONFLICT (link) DO NOTHING;")
            contagens[tabela] += 1
    sql.append("COMMIT;")
    destino = BACKEND_DIR / "database_sample.sql"
    destino.write_text("\n".join(sql) + "\n", encoding="utf-8")
    print(json.dumps({"fonte": fonte, "produtos": contagens, "bytes": destino.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
