"""Normalizacao de texto e preco extraidos das lojas."""

from __future__ import annotations

import re
import unicodedata
from html import unescape
from urllib.parse import urljoin, urlsplit
from typing import Any

# Remove caracteres de controle e espacos invisiveis (zero-width, BOM etc.)
# que aparecem com frequencia em nomes de produto raspados de HTML/JSON.
# Construido a partir dos code points (em vez de literais) para evitar
# caracteres invisiveis reais dentro do codigo-fonte.
_INVISIVEL_RANGES = (
    (0x0000, 0x001F),
    (0x007F, 0x007F),
    (0x00AD, 0x00AD),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2060),
    (0xFEFF, 0xFEFF),
)
_INVISIVEL_PATTERN = "[" + "".join(
    "\\u{0:04x}-\\u{1:04x}".format(lo, hi) if lo != hi else "\\u{0:04x}".format(lo)
    for lo, hi in _INVISIVEL_RANGES
) + "]"
_INVISIVEL = re.compile(_INVISIVEL_PATTERN)
_ESPACOS = re.compile(r"\s+")


def normalizar_espacos(value: Any) -> str:
    if value is None:
        return ""
    return _ESPACOS.sub(" ", _INVISIVEL.sub("", str(value))).strip()


def normalizar_nome(value: Any) -> str:
    return normalizar_espacos(value)


def inferir_categoria(nome: str) -> str | None:
    """Classifica apenas titulos reconheciveis, sem confundir acessorios."""
    texto = slugificar(nome).replace("-", " ")
    regras = (
        (r"^placa (?:de )?video\b", "Placa de video (VGA)"),
        (r"^processador\b", "Processador"),
        (r"^placa mae\b", "Placa-mae"),
        (r"^memoria (?:ram\b|.*\bddr[345]\b)", "Memoria RAM"),
        (r"^ssd\b", "SSD"), (r"^(?:hd|disco rigido)\b", "HD (Disco Rigido)"),
        (r"^fonte\b", "Fonte"), (r"^(?:water cooler|cooler)\b", "Cooler"),
        (r"^gabinete\b", "Gabinete"), (r"^monitor\b", "Monitor"),
        (r"^teclado\b", "Teclado"), (r"^mouse\b", "Mouse"),
        (r"^(?:pendrive|pen drive)\b", "Pendrive"),
    )
    return next((categoria for padrao, categoria in regras if re.search(padrao, texto)), None)


def normalizar_imagem_url(value: Any, base_url: str) -> str | None:
    """Aceita fotos HTTP e descarta placeholders e imagens embutidas."""
    if not isinstance(value, str):
        return None
    texto = unescape(value).strip()
    if not texto or texto.lower().startswith(("data:", "blob:", "javascript:")):
        return None
    url = urljoin(base_url, texto)
    partes = urlsplit(url)
    if partes.scheme not in {"http", "https"} or not partes.netloc:
        return None
    caminho = partes.path.lower()
    if caminho.endswith(".svg") or any(sinal in caminho for sinal in ("/icons/", "/icones/", "iconheart", "placeholder", "no-image", "no_image", "sem-imagem", "transparent", "spacer")):
        return None
    return url


def extrair_imagem_tag(tag: Any, base_url: str) -> str | None:
    """Prefere a maior foto do srcset e os atributos de carregamento tardio."""
    for atributo in ("data-srcset", "srcset"):
        candidatos = []
        for item in (tag.get(atributo) or "").split(","):
            partes = item.strip().split()
            if not partes:
                continue
            url = normalizar_imagem_url(partes[0], base_url)
            if url:
                descriptor = partes[1] if len(partes) > 1 else "1x"
                try:
                    tamanho = float(descriptor.rstrip("wx"))
                except ValueError:
                    tamanho = 0
                candidatos.append((tamanho, url))
        if candidatos:
            return max(candidatos, key=lambda item: item[0])[1]
    for atributo in ("data-src", "data-lazy-src", "data-original", "src"):
        url = normalizar_imagem_url(tag.get(atributo), base_url)
        if url:
            return url
    return None


def normalizar_preco(value: Any) -> float | None:
    """Aceita tanto numeros (JSON da loja) quanto texto 'R$ 1.234,56'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        preco = float(value)
        return preco if preco >= 0 else None
    texto = normalizar_espacos(value).replace("R$", "").strip()
    if not texto:
        return None
    texto = re.sub(r"[^0-9,.\-]", "", texto)
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        preco = float(texto)
    except ValueError:
        return None
    return preco if preco >= 0 else None


def slugificar(value: Any) -> str:
    texto = normalizar_espacos(value).lower()
    sem_acento = "".join(
        char for char in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "-", sem_acento).strip("-")
