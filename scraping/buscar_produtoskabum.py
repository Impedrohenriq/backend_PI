import logging
import math
import random
import re
import time
import unicodedata
import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models_kabum import Produto

# Configuração do logger
logging.basicConfig(level=logging.INFO)

# Configuração do banco de dados
DATABASE_URL = "postgresql://postgres:0608@localhost:5432/hunter_db"
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

MAX_PAGES_PER_CATEGORY = 20
CATEGORY_URLS = [
    ("monitor", "https://www.kabum.com.br/hardware/monitores"),
]
MAX_PRODUTOS = MAX_PAGES_PER_CATEGORY * 20 * len(CATEGORY_URLS)


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def parse_price(raw: str) -> float | None:
    numeric = re.sub(r"[^0-9,]", "", raw.replace("R$", "").strip()).replace(",", ".")
    try:
        return float(numeric)
    except ValueError:
        return None


def build_driver() -> webdriver.Chrome:
    options = ChromeOptions()
    options.add_argument("--remote-allow-origins=*")
    options.add_argument("--start-maximized")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    options.binary_location = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"

    service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def coletar_imagens_produto(driver: webdriver.Chrome, link_produto: str) -> list[str]:
    """
    Acessa a página do produto e coleta TODAS as imagens do carrossel/galeria.
    Retorna uma lista de URLs de imagens.
    """
    imagens = []
    try:
        driver.get(link_produto)
        time.sleep(random.uniform(1.5, 2.5))
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Tenta encontrar as miniaturas do carrossel da Kabum
        # Seletores comuns na Kabum para galeria de imagens
        thumb_containers = soup.find_all("div", class_=re.compile("thumb|miniatura|carousel|gallery", re.I))
        
        for container in thumb_containers:
            imgs = container.find_all("img")
            for img in imgs:
                src = img.get("data-src") or img.get("src") or img.get("data-original")
                if src:
                    if src.startswith("//"):
                        src = f"https:{src}"
                    elif src.startswith("/"):
                        src = f"https://www.kabum.com.br{src}"
                    # Filtra imagens muito pequenas ou placeholders
                    if "placeholder" not in src.lower() and "loading" not in src.lower():
                        if src not in imagens:
                            imagens.append(src)
        
        # Se não encontrou nas miniaturas, tenta a imagem principal e outras
        if len(imagens) < 2:
            # Busca todas as imagens na área do produto
            produto_area = soup.find("div", class_=re.compile("product|produto", re.I))
            if produto_area:
                all_imgs = produto_area.find_all("img")
                for img in all_imgs:
                    src = img.get("data-src") or img.get("src") or img.get("data-zoom") or img.get("data-large")
                    if src:
                        if src.startswith("//"):
                            src = f"https:{src}"
                        elif src.startswith("/"):
                            src = f"https://www.kabum.com.br{src}"
                        # Filtra por tamanho mínimo e placeholders
                        if "placeholder" not in src.lower() and "loading" not in src.lower() and "icon" not in src.lower():
                            if src not in imagens:
                                imagens.append(src)
        
        # Tenta também pegar do JSON-LD se disponível
        script_tags = soup.find_all("script", type="application/ld+json")
        for script in script_tags:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    # Pode ter uma imagem única ou array
                    if "image" in data:
                        img_data = data["image"]
                        if isinstance(img_data, list):
                            for img_url in img_data:
                                if img_url and img_url not in imagens:
                                    imagens.append(img_url)
                        elif isinstance(img_data, str) and img_data not in imagens:
                            imagens.append(img_data)
            except:
                pass
        
        logging.info(f"Coletadas {len(imagens)} imagens para o produto")
        
    except Exception as e:
        logging.warning(f"Erro ao coletar imagens do produto {link_produto}: {e}")
    
    return imagens[:10]  # Limita a 10 imagens por produto


def coletar_produtos(
    max_produtos: int,
    categorias: list[tuple[str, str]] = CATEGORY_URLS,
) -> list[dict]:
    coletados: list[dict] = []

    for categoria_nome, base_url in categorias:
        if len(coletados) >= max_produtos:
            break

        driver = build_driver()
        try:
            driver.get(base_url)
            time.sleep(random.uniform(1.5, 2.5))
            soup = BeautifulSoup(driver.page_source, "html.parser")

            contador_tag = soup.find("div", id="listingCount")
            if not contador_tag:
                logging.warning(
                    "Não foi possível identificar o total de produtos na primeira página de %s.",
                    categoria_nome,
                )
                total_paginas = MAX_PAGES_PER_CATEGORY
            else:
                total_produtos = int(re.search(r"\d+", contador_tag.text).group())
                total_paginas = max(1, math.ceil(total_produtos / 20))
                total_paginas = min(total_paginas, MAX_PAGES_PER_CATEGORY)

            for pagina in range(1, total_paginas + 1):
                if len(coletados) >= max_produtos:
                    break

                logging.info(
                    "Capturando página %s de %s (%s)",
                    pagina,
                    total_paginas,
                    categoria_nome,
                )
                url = (
                    f"{base_url}?page_number={pagina}&page_size=20&"
                    "facet_filters=&sort=most_searched"
                )
                driver.get(url)
                time.sleep(random.uniform(1, 1.5))

                try:
                    WebDriverWait(driver, 12).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "article.productCard"))
                    )
                except TimeoutException:
                    logging.warning("Timeout aguardando produtos na página %s (%s)", pagina, categoria_nome)
                    continue

                soup = BeautifulSoup(driver.page_source, "html.parser")
                cards = soup.find_all("article", class_=re.compile("productCard"))

                for card in cards:
                    nome_tag = card.find("span", class_=re.compile("nameCard"))
                    preco_tag = card.find("span", class_=re.compile("priceCard"))
                    link_tag = card.find("a", href=True)
                    img_tag = card.find("img")

                    if not nome_tag or not preco_tag or not link_tag:
                        continue

                    nome = normalize_text(nome_tag.get_text(strip=True))
                    preco = parse_price(preco_tag.get_text(strip=True))
                    if preco is None:
                        continue

                    link_produto = urljoin("https://www.kabum.com.br", link_tag.get("href"))

                    # Imagem principal do card
                    imagem_url = None
                    if img_tag:
                        imagem_url = img_tag.get("data-src") or img_tag.get("src")
                        if imagem_url and imagem_url.startswith("//"):
                            imagem_url = f"https:{imagem_url}"
                    if not imagem_url:
                        # fallback: verificar se há script com imagem explicita
                        script_tag = card.find("script", type="application/ld+json")
                        if script_tag:
                            try:
                                data = json.loads(script_tag.string)
                                imagem_url = data.get("image")
                            except Exception:
                                imagem_url = None

                    # Coleta TODAS as imagens entrando na página do produto
                    logging.info(f"Coletando imagens do produto: {nome[:50]}...")
                    todas_imagens = coletar_imagens_produto(driver, link_produto)
                    
                    # Se não conseguiu coletar imagens da página, usa a do card
                    if not todas_imagens and imagem_url:
                        todas_imagens = [imagem_url]

                    coletados.append(
                        {
                            "nome": nome,
                            "preco": preco,
                            "link": link_produto,
                            "imagem_url": imagem_url or (todas_imagens[0] if todas_imagens else None),
                            "imagens_urls": todas_imagens,
                            "categoria": categoria_nome,
                        }
                    )

                    if len(coletados) >= max_produtos:
                        break
        finally:
            driver.quit()

    return coletados


def salvar_produtos(produtos: list[dict]) -> None:
    session = Session()
    try:
        for item in produtos:
            existente = (
                session.query(Produto)
                .filter_by(nome=item["nome"], link=item["link"])
                .first()
            )

            # Converte lista de imagens para JSON
            imagens_json = json.dumps(item.get("imagens_urls", [])) if item.get("imagens_urls") else None

            if existente:
                existente.preco = item["preco"]
                if item["imagem_url"]:
                    existente.imagem_url = item["imagem_url"]
                if imagens_json:
                    existente.imagens_urls = imagens_json
            else:
                session.add(
                    Produto(
                        nome=item["nome"],
                        preco=item["preco"],
                        link=item["link"],
                        imagem_url=item["imagem_url"],
                        imagens_urls=imagens_json,
                    )
                )

        session.commit()
    finally:
        session.close()


def index(max_produtos: int = MAX_PRODUTOS) -> None:
    produtos = coletar_produtos(max_produtos)
    if not produtos:
        logging.warning("Nenhum produto foi coletado da Kabum.")
        return

    salvar_produtos(produtos)
    logging.info("%s produtos da Kabum foram gravados no banco.", len(produtos))


if __name__ == "__main__":
    index()
