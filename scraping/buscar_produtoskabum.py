"""Scraper de produtos da Kabum.

Arquitetura em duas etapas, adaptada ao site atual (Next.js):

1. Listagem: usa o Scrapling (sessao de navegador real) para abrir cada
   pagina de categoria e coletar os links "/produto/<id>/<slug>" - unico
   seletor estavel, ja que a Kabum usa classes CSS geradas (styled
   components) que mudam a cada deploy.
2. Detalhe: cada pagina de produto da Kabum e renderizada no servidor
   (Next.js) e embute o objeto completo do produto em JSON dentro de
   <script id="__NEXT_DATA__">. Isso e lido com uma requisicao HTTP comum
   (sem navegador), o que e muito mais rapido e retorna nome, preco e a
   galeria de imagens completa (4 resolucoes) de forma estruturada, em
   vez de tentar adivinhar seletores de carrossel via BeautifulSoup.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from configuracao import BACKEND_DIR, get_config
from db_produtos import preparar_schema, salvar_produtos_kabum
from normalizacao import normalizar_espacos, normalizar_nome, normalizar_preco, normalizar_imagem_url

logger = logging.getLogger(__name__)

BASE_URL = "https://www.kabum.com.br"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
PAGE_SIZE = 20

# Categorias principais de hardware (nome de exibicao -> slug da URL),
# confirmadas ao vivo em kabum.com.br/hardware/<slug>.
CATEGORIAS_KABUM: tuple[tuple[str, str], ...] = (
    ("Placa de video (VGA)", "placa-de-video-vga"),
    ("Processador", "processadores"),
    ("Placa-mae", "placas-mae"),
    ("Memoria RAM", "memoria-ram"),
    ("SSD", "ssd-2-5"),
    ("HD (Disco Rigido)", "disco-rigido-hd"),
    ("Fonte", "fontes"),
    ("Cooler", "coolers"),
    ("Gabinete", "gabinetes"),
    ("Monitor", "monitores"),
)

_BLOQUEIO_SINAIS = (
    "captcha",
    "unusual traffic",
    "atividade incomum",
    "verify you are human",
    "confirme que voce nao e um robo",
    "access denied",
)


def _config():
    return get_config()


def detectar_bloqueio(texto: str) -> bool:
    normalizado = normalizar_espacos(texto).lower()
    return any(sinal in normalizado for sinal in _BLOQUEIO_SINAIS)


def _is_transient_error(exc: Exception) -> bool:
    texto = f"{type(exc).__name__}: {exc}".lower()
    sinais = (
        "timeout",
        "timed out",
        "net::err_",
        "connection reset",
        "connection refused",
        "temporarily unavailable",
        "target closed",
    )
    return any(sinal in texto for sinal in sinais)


def salvar_html_falha(conteudo: str, identificador: str) -> Path | None:
    if not _config().scraper_save_failure_html:
        return None
    destino = BACKEND_DIR / "scraping" / "dados" / "falhas"
    destino.mkdir(parents=True, exist_ok=True)
    seguro = re.sub(r"[^\w.-]+", "_", identificador)[:80]
    caminho = destino / f"{seguro}.html"
    caminho.write_text(conteudo, encoding="utf-8", errors="ignore")
    return caminho


def _criar_sessao_navegador():
    from scrapling.fetchers import DynamicSession, StealthySession

    config = _config()
    classe = StealthySession if config.scraper_fetcher == "stealthy" else DynamicSession
    return classe(headless=config.scraper_headless, timeout=config.scraper_timeout_ms)


def _extrair_total_produtos(texto_pagina: str) -> int | None:
    match = re.search(r"([\d.]+)\s*produtos?\b", texto_pagina, re.I)
    if not match:
        return None
    try:
        return int(match.group(1).replace(".", ""))
    except ValueError:
        return None


def _coletar_links_categoria(session, categoria_nome: str, slug: str, max_paginas: int) -> list[str]:
    config = _config()
    base_url = f"{BASE_URL}/hardware/{slug}"
    links: list[str] = []
    vistos: set[str] = set()
    total_produtos: int | None = None

    for pagina in range(1, max_paginas + 1):
        url = f"{base_url}?page_number={pagina}&page_size={PAGE_SIZE}"
        pagina_carregada = None
        for tentativa in range(config.scraper_max_retries + 1):
            try:
                pagina_carregada = session.fetch(
                    url,
                    network_idle=False,
                    wait_selector='a[href*="/produto/"]',
                    wait_selector_state="attached",
                    wait=1000,
                    timeout=config.scraper_timeout_ms,
                )
                break
            except Exception as exc:
                if detectar_bloqueio(str(exc)) or not _is_transient_error(exc) or tentativa >= config.scraper_max_retries:
                    logger.warning("Falha ao carregar %s: %s", url, exc)
                    pagina_carregada = None
                    break
                logger.info("Retry %s/%s para %s", tentativa + 1, config.scraper_max_retries, url)
                time.sleep(min(8, 0.75 * (2**tentativa)))

        if pagina_carregada is None:
            break

        corpo = getattr(pagina_carregada, "text", "") or ""
        corpo_texto = corpo() if callable(corpo) else corpo
        if detectar_bloqueio(str(corpo_texto)):
            logger.error("Bloqueio detectado na categoria %s (pagina %s); interrompendo.", categoria_nome, pagina)
            salvar_html_falha(str(corpo_texto), f"bloqueio_{slug}_p{pagina}")
            break

        if total_produtos is None:
            total_produtos = _extrair_total_produtos(str(corpo_texto))

        hrefs = pagina_carregada.css('a[href*="/produto/"]::attr(href)')
        novos = 0
        for href in hrefs:
            href = str(href)
            if href not in vistos:
                vistos.add(href)
                links.append(href)
                novos += 1

        logger.info("%s pagina %s: %s links novos (total %s)", categoria_nome, pagina, novos, len(links))

        if novos == 0:
            break
        if total_produtos is not None and len(links) >= total_produtos:
            break

    return links


def _extrair_produto_next_data(html: str) -> dict | None:
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S
    )
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload.get("props", {}).get("pageProps", {}).get("product")


def _extrair_imagens(produto_json: dict) -> tuple[str | None, list[str]]:
    imagens: list[str] = []
    for media in produto_json.get("medias") or []:
        if not isinstance(media, dict):
            continue
        if media.get("type") and media.get("type") != "image":
            continue
        resolucoes = media.get("images") or {}
        if not isinstance(resolucoes, dict):
            continue
        url = next((foto for chave in ("gg", "g", "m", "p")
                    if (foto := normalizar_imagem_url(resolucoes.get(chave), BASE_URL))), None)
        if url and url not in imagens:
            imagens.append(url)
    thumbnail = normalizar_imagem_url(produto_json.get("thumbnail"), BASE_URL)
    imagem_principal = imagens[0] if imagens else thumbnail
    if not imagens and thumbnail:
        imagens.append(thumbnail)
    return imagem_principal, imagens[:12]


def coletar_detalhe_produto(sessao_http: requests.Session, href: str, categoria: str) -> dict | None:
    link = urljoin(BASE_URL, href)
    config = _config()
    for tentativa in range(config.scraper_max_retries + 1):
        try:
            resposta = sessao_http.get(link, timeout=20)
            resposta.raise_for_status()
            break
        except Exception as exc:
            if not _is_transient_error(exc) or tentativa >= config.scraper_max_retries:
                logger.warning("Falha ao obter detalhe de %s: %s", link, exc)
                return None
            time.sleep(min(6, 0.5 * (2**tentativa)))
    else:
        return None

    if detectar_bloqueio(resposta.text):
        logger.warning("Bloqueio detectado na pagina de detalhe: %s", link)
        salvar_html_falha(resposta.text, f"bloqueio_detalhe_{href}")
        return None

    produto_json = _extrair_produto_next_data(resposta.text)
    if not produto_json:
        logger.warning("Nao foi possivel extrair dados estruturados de %s", link)
        return None

    nome = normalizar_nome(produto_json.get("title"))
    if not nome:
        return None

    precos = produto_json.get("prices") or {}
    preco = normalizar_preco(precos.get("priceWithDiscount")) or normalizar_preco(precos.get("price")) or normalizar_preco(produto_json.get("price"))
    if preco is None:
        return None

    imagem_url, imagens_urls = _extrair_imagens(produto_json)

    return {
        "nome": nome,
        "preco": preco,
        "link": link,
        "imagem_url": imagem_url,
        "imagens_urls": imagens_urls,
        "categoria": categoria,
    }


def coletar_categoria(session, sessao_http: requests.Session, categoria_nome: str, slug: str, max_paginas: int) -> list[dict]:
    config = _config()
    links = _coletar_links_categoria(session, categoria_nome, slug, max_paginas)
    if not links:
        logger.warning("Nenhum link de produto encontrado para %s", categoria_nome)
        return []

    produtos: list[dict] = []
    for indice, href in enumerate(links):
        item = coletar_detalhe_produto(sessao_http, href, categoria_nome)
        if item:
            produtos.append(item)
        if config.scraper_min_delay_seconds and indice < len(links) - 1:
            time.sleep(random.uniform(config.scraper_min_delay_seconds, config.scraper_max_delay_seconds))

    logger.info("%s: %s/%s produtos com detalhes coletados", categoria_nome, len(produtos), len(links))
    return produtos


def coletar_produtos(categorias: tuple[tuple[str, str], ...] = CATEGORIAS_KABUM) -> list[dict]:
    """Mantido para compatibilidade/testes: coleta tudo em memoria, sem salvar.

    O fluxo principal (`index`) nao usa esta funcao — ele salva categoria a
    categoria via `index`, para nao perder progresso em execucoes longas.
    """
    config = _config()
    coletados: list[dict] = []
    sessao_http = requests.Session()
    sessao_http.headers.update({"User-Agent": USER_AGENT})

    with _criar_sessao_navegador() as session:
        for categoria_nome, slug in categorias:
            logger.info("Iniciando categoria: %s", categoria_nome)
            try:
                produtos = coletar_categoria(
                    session, sessao_http, categoria_nome, slug, config.scraper_max_paginas_por_categoria
                )
                coletados.extend(produtos)
            except Exception:
                logger.exception("Falha inesperada na categoria %s", categoria_nome)

    return coletados


def index(categorias: tuple[tuple[str, str], ...] = CATEGORIAS_KABUM) -> int:
    """Roda o scraping salvando categoria a categoria.

    Uma execucao completa (10 categorias, ate 20 paginas cada) pode levar
    mais de uma hora; salvar ao final de cada categoria, em vez de so no
    fim de tudo, evita perder o progresso inteiro se o processo cair no
    meio do caminho.
    """
    if not preparar_schema():
        logger.error("Nao foi possivel preparar o schema do banco; abortando.")
        return 0

    config = _config()
    sessao_http = requests.Session()
    sessao_http.headers.update({"User-Agent": USER_AGENT})

    total_salvos = 0
    with _criar_sessao_navegador() as session:
        for categoria_nome, slug in categorias:
            logger.info("Iniciando categoria: %s", categoria_nome)
            try:
                produtos = coletar_categoria(
                    session, sessao_http, categoria_nome, slug, config.scraper_max_paginas_por_categoria
                )
            except Exception:
                logger.exception("Falha inesperada na categoria %s; pulando.", categoria_nome)
                continue

            if not produtos:
                logger.warning("Nenhum produto coletado para %s.", categoria_nome)
                continue

            salvos, ignorados = salvar_produtos_kabum(produtos)
            total_salvos += salvos
            logger.info(
                "%s: %s produtos gravados/atualizados (%s ignorados). Total ate agora: %s",
                categoria_nome, salvos, ignorados, total_salvos,
            )

    if total_salvos == 0:
        logger.warning("Nenhum produto foi coletado da Kabum.")
    return total_salvos


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    index()
