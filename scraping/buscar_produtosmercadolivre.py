from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models_mercadolivre import ProdutoMercadoLivre
import requests
from bs4 import BeautifulSoup
import time

# URL do banco de dados
DATABASE_URL = "postgresql://postgres:0608@localhost/hunter_db"

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

MAX_PAGINAS_POR_TERMO = 10
TERMOS_BUSCA = ["teclado"]
MAX_PRODUTOS = MAX_PAGINAS_POR_TERMO * 50 * len(TERMOS_BUSCA)


# Headers para parecer um navegador real
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/114.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}


def buscar_produtos(url: str):
    """
    Faz a requisição HTTP, interpreta o HTML e retorna
    uma lista de dicionários com produto / preço / link.
    """
    print(f"\n[INFO] Acessando URL: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        print(f"[ERRO] Falha na requisição: {e}")
        return []

    if resp.status_code != 200:
        print(f"[ERRO] Status HTTP {resp.status_code} ao acessar {url}")
        return []

    soup = BeautifulSoup(resp.content, "html.parser")

    # Tenta localizar os "cards" de produto com vários seletores possíveis
    # porque o Mercado Livre vive mudando as classes.
    candidates = []

    # Tentativa 1: layout antigo
    candidates.extend(soup.select("li.ui-search-layout__item"))

    # Tentativa 2: result wrapper mais novo
    candidates.extend(soup.select("li.ui-search-result__wrapper"))

    # Tentativa 3: qualquer <li> dentro de lista de resultados
    if not candidates:
        listas = soup.select("ol.ui-search-layout, ul.ui-search-layout")
        for lista in listas:
            candidates.extend(lista.find_all("li", recursive=False))

    print(f"[INFO] Produtos encontrados no HTML bruto: {len(candidates)}")

    itens = []

    for li in candidates:
        # ------------ NOME E LINK ------------
        # tenta achar um <a> que represente o link do produto
        a_tag = (
            li.select_one("a.ui-search-link")
            or li.select_one("a.ui-search-result__content")
            or li.find("a", href=True)
        )

        if not a_tag:
            continue

        produto = a_tag.get_text(strip=True)
        link = a_tag.get("href", "").strip()

        img_tag = (
            li.select_one("img.ui-search-result-image__element")
            or li.select_one("img.ui-search-result__image")
            or li.find("img")
        )

        imagem_url = None
        if img_tag:
            imagem_url = (
                img_tag.get("data-src")
                or img_tag.get("src")
                or img_tag.get("data-srcset")
            )
            if imagem_url and " " in imagem_url:
                imagem_url = imagem_url.split(" ")[0]

        # ------------ PREÇO ------------
        # tenta capturar parte fracionária do preço (ex: 1.234)
        preco_tag = (
            li.select_one("span.ui-search-price__fraction")
            or li.select_one("span.andes-money-amount__fraction")
            or li.select_one("span.andes-money-amount__fraction--compact")
        )

        if not preco_tag:
            # Se não achar, tenta pegar qualquer span com dígitos
            preco_tag = li.find("span")
        
        if preco_tag:
            preco_texto = preco_tag.get_text(strip=True)
            # remove separadores de milhar e troca vírgula por ponto
            preco_texto = preco_texto.replace(".", "").replace(",", ".")
        else:
            preco_texto = "0"

        try:
            preco = float(preco_texto)
        except ValueError:
            preco = 0.0

        if not produto or preco == 0.0 or not link:
            # pula entradas inválidas
            continue

        itens.append({
            "produto": produto,
            "preco": preco,
            "link": link,
            "imagem_url": imagem_url,
        })

    print(f"[INFO] Itens válidos processados: {len(itens)}")
    return itens


def processar_termo(
    termo: str,
    session: "Session",
    limite: int,
    max_paginas: int = MAX_PAGINAS_POR_TERMO,
) -> int:
    """Processa um termo de busca específico, retornando quantos registros novos foram inseridos."""
    base_url = f"https://lista.mercadolivre.com.br/{termo}"
    page_number = 1
    inseridos = 0

    while page_number <= max_paginas and inseridos < limite:
        print("\n========================")
        print(f"[INFO] ({termo}) Buscando na página {page_number}/{max_paginas}")
        print("========================")

        url = f"{base_url}_Desde_{(page_number - 1) * 50}"
        itens = buscar_produtos(url)

        if not itens:
            print(f"[AVISO] ({termo}) Nenhum item retornado nesta página. Encerrando paginação.")
            break

        for item in itens:
            existente = (
                session.query(ProdutoMercadoLivre)
                .filter_by(nome=item["produto"], link=item["link"])
                .first()
            )

            if existente:
                if item["imagem_url"] and existente.imagem_url != item["imagem_url"]:
                    existente.imagem_url = item["imagem_url"]
                if existente.preco != item["preco"]:
                    novo = ProdutoMercadoLivre(
                        nome=item["produto"],
                        preco=item["preco"],
                        link=item["link"],
                        imagem_url=item["imagem_url"],
                    )
                    session.add(novo)
                    print(
                        f"[UPDATE] ({termo}) Novo preço registrado para: {item['produto']} -> {item['preco']}"
                    )
                    inseridos += 1
                else:
                    print(f"[SKIP] ({termo}) Produto já existe com mesmo preço: {item['produto']}")
            else:
                novo = ProdutoMercadoLivre(
                    nome=item["produto"],
                    preco=item["preco"],
                    link=item["link"],
                    imagem_url=item["imagem_url"],
                )
                session.add(novo)
                print(f"[INSERT] ({termo}) Produto inserido: {item['produto']} - {item['preco']}")
                inseridos += 1

            if inseridos >= limite:
                break

        session.commit()

        if inseridos >= limite:
            print(f"[INFO] ({termo}) Limite de produtos coletados atingido para o termo.")
            break

        page_number += 1
        time.sleep(2)

    return inseridos


def buscar_multiplos_termos(max_produtos: int = MAX_PRODUTOS) -> None:
    session = Session()
    try:
        inseridos_total = 0
        for termo in TERMOS_BUSCA:
            if inseridos_total >= max_produtos:
                break

            limite_restante = max_produtos - inseridos_total
            inseridos = processar_termo(termo, session, limite_restante)
            inseridos_total += inseridos

        print(f"\n[INFO] Total de produtos inseridos/atualizados: {inseridos_total}")
    finally:
        session.close()
        print("[INFO] Conexão com o banco encerrada.")


if __name__ == "__main__":
    buscar_multiplos_termos(MAX_PRODUTOS)
