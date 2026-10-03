"""Repara fotos antigas usando exclusivamente dados da pagina do produto."""
import json
import logging
import time

from bs4 import BeautifulSoup
from buscar_produtoskabum import _criar_sessao_navegador, _extrair_produto_next_data, _extrair_imagens
from db_produtos import get_connection
from normalizacao import normalizar_imagem_url


def main():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, link, imagem_url FROM produtos_kabum ORDER BY id")
            pendentes = [(id_, link) for id_, link, foto in cursor.fetchall()
                         if not normalizar_imagem_url(foto, link)]
        print(f"Fotos para corrigir: {len(pendentes)}", flush=True)
        with _criar_sessao_navegador() as session:
            for id_, link in pendentes:
                try:
                    resposta = session.fetch(link, wait=1000, network_idle=False)
                    html = resposta.body
                    if isinstance(html, bytes):
                        html = html.decode("utf-8", errors="replace")
                    produto = _extrair_produto_next_data(html)
                    foto, fotos = _extrair_imagens(produto) if produto else (None, [])
                    if not foto and resposta.status == 200:
                        # Open Graph descreve o produto principal, nao os recomendados.
                        tag = BeautifulSoup(html, "html.parser").select_one('meta[property="og:image"]')
                        foto = normalizar_imagem_url(tag.get("content"), link) if tag else None
                        fotos = [foto] if foto else []
                    if foto:
                        with conn.cursor() as cursor:
                            cursor.execute("UPDATE produtos_kabum SET imagem_url=%s, imagens_urls=%s WHERE id=%s",
                                           (foto, json.dumps(fotos), id_))
                        conn.commit()
                        print(f"Corrigido {id_}: {foto}", flush=True)
                    else:
                        with conn.cursor() as cursor:
                            cursor.execute("UPDATE produtos_kabum SET imagem_url=NULL, imagens_urls=NULL WHERE id=%s", (id_,))
                        conn.commit()
                        print(f"Sem foto confiavel {id_} (HTTP {resposta.status})", flush=True)
                except Exception as exc:
                    conn.rollback()
                    print(f"Falha {id_}: {exc}", flush=True)
                time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
