"""Coleta extensivel de lojas: listagem com Scrapling e detalhe do produto."""
from __future__ import annotations

import argparse
import json
import logging
import math
import random
import re
import time
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from buscar_produtoskabum import _criar_sessao_navegador, detectar_bloqueio, salvar_html_falha, _is_transient_error
from configuracao import get_config
from db_produtos import preparar_schema, salvar_produtos_lojas
from normalizacao import normalizar_nome, normalizar_preco, normalizar_imagem_url, extrair_imagem_tag

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Loja:
    nome: str
    dominio: str
    busca: str
    produto_pattern: str


LOJAS = {
    "amazon": Loja("Amazon", "www.amazon.com.br", "https://www.amazon.com.br/s?k={termo}&page={pagina}", r"/(?:dp|gp/product)/[A-Z0-9]{10}"),
    "magalu": Loja("Magazine Luiza", "www.magazineluiza.com.br", "https://www.magazineluiza.com.br/busca/{termo}/?page={pagina}", r"/p/[^/]+"),
    "pichau": Loja("Pichau", "www.pichau.com.br", "https://www.pichau.com.br/search?q={termo}&page={pagina}", r"^/[^/]+(?:-[^/]+)+/?$"),
    "terabyte": Loja("Terabyte", "www.terabyteshop.com.br", "https://www.terabyteshop.com.br/busca?str={termo}&pagina={pagina}", r"/produto/\d+"),
}

# Mesmos nomes de categoria usados pela Kabum e pelo filtro da API.
TERMOS = (
    ("placa de video", "Placa de video (VGA)"), ("processador", "Processador"),
    ("placa mae", "Placa-mae"), ("memoria ram", "Memoria RAM"),
    ("ssd", "SSD"), ("hd interno", "HD (Disco Rigido)"),
    ("fonte pc", "Fonte"), ("cooler", "Cooler"),
    ("gabinete", "Gabinete"), ("monitor", "Monitor"),
    ("teclado", "Teclado"), ("mouse", "Mouse"), ("pendrive", "Pendrive"),
)


def link_produto(href: str, loja: Loja) -> str | None:
    partes = urlsplit(urljoin(f"https://{loja.dominio}", href))
    if partes.scheme not in {"http", "https"} or partes.hostname != loja.dominio:
        return None
    match = re.search(loja.produto_pattern, partes.path, re.I)
    if not match:
        return None
    caminho = partes.path
    if loja.nome == "Amazon":
        caminho = "/dp/" + match.group().rstrip("/").split("/")[-1]
    return urlunsplit(("https", loja.dominio, caminho, "", ""))


def carregar(session, url: str, identificador: str) -> BeautifulSoup | None:
    config = get_config()
    for tentativa in range(config.scraper_max_retries + 1):
        try:
            resposta = session.fetch(url, network_idle=False, wait=1500, timeout=config.scraper_timeout_ms)
            html = resposta.body
            if isinstance(html, bytes):
                html = html.decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            # Examina texto visivel para nao confundir scripts de CAPTCHA com bloqueios.
            for script in soup.select("script, style"):
                if script.get("type") != "application/ld+json":
                    script.decompose()
            if resposta.status in (403, 429) or detectar_bloqueio(soup.get_text(" ", strip=True)):
                salvar_html_falha(str(html), identificador)
                logger.warning("Bloqueio em %s; coleta desta busca interrompida", url)
                return None
            if resposta.status >= 400:
                logger.warning("HTTP %s em %s", resposta.status, url)
                return None
            return soup
        except Exception as exc:
            if tentativa >= config.scraper_max_retries or not _is_transient_error(exc):
                logger.warning("Falha em %s: %s", url, exc)
                return None
            time.sleep(min(8, 2 ** tentativa))
    return None


def produtos_estruturados(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        fila = list(payload) if isinstance(payload, list) else [payload]
        while fila:
            item = fila.pop(0)
            if not isinstance(item, dict):
                continue
            tipo = item.get("@type", [])
            if "Product" in (tipo if isinstance(tipo, list) else [tipo]):
                yield item
            # Nao percorre ItemList/recomendacoes: somente entidades principais.
            grafo = item.get("@graph", [])
            if isinstance(grafo, list):
                fila.extend(grafo)
            principal = item.get("mainEntity")
            if isinstance(principal, dict):
                fila.append(principal)


def extrair_produto(soup, link: str, loja: Loja, categoria: str) -> dict | None:
    nome = preco = None
    imagens = []
    for produto in produtos_estruturados(soup):
        url = produto.get("url")
        if url and link_produto(str(url), loja) != link:
            continue
        offers = produto.get("offers") or []
        offers = offers if isinstance(offers, list) else [offers]
        for oferta in offers:
            if not isinstance(oferta, dict) or oferta.get("priceCurrency", "BRL") != "BRL":
                continue
            # Nao usa lowPrice de AggregateOffer como preco do item.
            preco = normalizar_preco(oferta.get("price"))
            if preco is not None and math.isfinite(preco) and preco > 0:
                break
            preco = None
        if preco is None:
            continue
        nome = normalizar_nome(produto.get("name"))
        fotos = produto.get("image") or []
        fotos = fotos if isinstance(fotos, list) else [fotos]
        for foto in fotos:
            if isinstance(foto, dict):
                foto = foto.get("contentUrl") or foto.get("url")
            foto = normalizar_imagem_url(foto, link)
            if foto and foto not in imagens:
                imagens.append(foto)
        break

    if loja.nome == "Amazon":
        titulo = soup.select_one("#productTitle")
        if titulo:
            nome = normalizar_nome(titulo.get_text(" ", strip=True))
        valor = soup.select_one("#corePriceDisplay_desktop_feature_div .a-price .a-offscreen, #corePrice_feature_div .a-price .a-offscreen")
        if valor:
            preco = normalizar_preco(valor.get_text(strip=True))
        foto = soup.select_one("#landingImage, #imgBlkFront")
        if foto:
            principal = normalizar_imagem_url(foto.get("data-old-hires"), link) or extrair_imagem_tag(foto, link)
            if principal:
                imagens = [principal] + [imagem for imagem in imagens if imagem != principal]

    if not nome or preco is None or not math.isfinite(preco) or preco <= 0:
        logger.warning("Produto sem nome/preco confiavel: %s", link)
        return None
    if not imagens:
        foto = soup.select_one('meta[property="og:image"]')
        imagem = normalizar_imagem_url(foto.get("content"), link) if foto else None
        if imagem:
            imagens.append(imagem)
    return dict(nome=nome, preco=preco, link=link, categoria=categoria,
                origem=loja.nome, imagem_url=imagens[0] if imagens else None,
                imagens_urls=imagens[:12])


def pausa():
    config = get_config()
    time.sleep(random.uniform(config.scraper_min_delay_seconds, config.scraper_max_delay_seconds))


def index(lojas, termos, max_paginas: int, max_produtos: int) -> int:
    if not preparar_schema():
        raise RuntimeError("Nao foi possivel preparar o banco")
    total = 0
    with _criar_sessao_navegador() as session:
        for chave in lojas:
            loja = LOJAS[chave]
            vistos = set()
            for termo, categoria in termos:
                gravados = 0
                for pagina in range(1, max_paginas + 1):
                    url = loja.busca.format(termo=quote(termo, safe=""), pagina=pagina)
                    soup = carregar(session, url, f"{chave}_busca_{termo}_{pagina}")
                    if soup is None:
                        break
                    links = list(dict.fromkeys(link for a in soup.select("a[href]")
                                               if (link := link_produto(a["href"], loja)) and link not in vistos))
                    if not links:
                        logger.warning("%s: nenhum link novo para %s pagina %s", loja.nome, termo, pagina)
                        break
                    # Persiste cada detalhe para preservar progresso.
                    for link in links:
                        vistos.add(link)
                        pausa()
                        detalhe = carregar(session, link, f"{chave}_detalhe_{len(vistos)}")
                        if detalhe is None:
                            break
                        item = extrair_produto(detalhe, link, loja, categoria)
                        if item:
                            salvos, _ = salvar_produtos_lojas([item])
                            total += salvos
                            gravados += salvos
                        if gravados >= max_produtos:
                            break
                    else:
                        pausa()
                        continue
                    break
                logger.info("%s / %s: %s produtos salvos", loja.nome, termo, gravados)
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lojas", nargs="+", choices=LOJAS, default=list(LOJAS))
    parser.add_argument("--termos", nargs="+", help="Ex.: --termos 'teclado' 'mouse'")
    parser.add_argument("--paginas", type=int, default=1)
    parser.add_argument("--limite", type=int, default=20, help="Produtos por termo/loja")
    args = parser.parse_args()
    if args.paginas < 1 or args.limite < 1:
        parser.error("--paginas e --limite devem ser positivos")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    categorias = dict(TERMOS)
    termos = [(termo, categorias.get(termo)) for termo in args.termos] if args.termos else TERMOS
    logger.info("Total salvo: %s", index(args.lojas, termos, args.paginas, args.limite))
