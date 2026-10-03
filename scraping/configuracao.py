"""Configuração do scraper de produtos, carregada de variáveis de ambiente."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - útil antes da instalação
    load_dotenv = None

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "sim", "on"}:
        return True
    if normalized in {"0", "false", "no", "nao", "não", "off"}:
        return False
    raise ValueError(f"{name} deve ser booleano")


def _int(name: str, default: int, minimum: int = 0) -> int:
    value = os.getenv(name)
    try:
        parsed = default if value is None or not value.strip() else int(value)
    except ValueError as exc:
        raise ValueError(f"{name} deve ser inteiro") from exc
    if parsed < minimum:
        raise ValueError(f"{name} deve ser maior ou igual a {minimum}")
    return parsed


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    value = os.getenv(name)
    try:
        parsed = default if value is None or not value.strip() else float(value)
    except ValueError as exc:
        raise ValueError(f"{name} deve ser numérico") from exc
    if parsed < minimum:
        raise ValueError(f"{name} deve ser maior ou igual a {minimum}")
    return parsed


@dataclass(frozen=True)
class Configuracao:
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "postgres"
    pg_password: str = "0608"
    pg_database: str = "hunter_db"
    scraper_fetcher: str = "dynamic"
    scraper_headless: bool = True
    scraper_timeout_ms: int = 60000
    scraper_max_paginas_por_categoria: int = 20
    scraper_min_delay_seconds: float = 1.0
    scraper_max_delay_seconds: float = 2.5
    scraper_max_retries: int = 3
    scraper_save_failure_html: bool = True


def carregar_configuracao() -> Configuracao:
    if load_dotenv:
        load_dotenv(BACKEND_DIR / ".env", override=False)
    fetcher = os.getenv("SCRAPER_FETCHER", "dynamic").strip().lower()
    if fetcher not in {"dynamic", "stealthy"}:
        raise ValueError("SCRAPER_FETCHER deve ser dynamic ou stealthy")
    minimum_delay = _float("SCRAPER_MIN_DELAY_SECONDS", 1.0)
    maximum_delay = _float("SCRAPER_MAX_DELAY_SECONDS", 2.5)
    if maximum_delay < minimum_delay:
        raise ValueError("SCRAPER_MAX_DELAY_SECONDS deve ser >= SCRAPER_MIN_DELAY_SECONDS")
    return Configuracao(
        pg_host=os.getenv("PG_HOST", "localhost"),
        pg_port=_int("PG_PORT", 5432, 1),
        pg_user=os.getenv("PG_USER", "postgres"),
        pg_password=os.getenv("PG_PASSWORD", "0608"),
        pg_database=os.getenv("PG_DATABASE", "hunter_db"),
        scraper_fetcher=fetcher,
        scraper_headless=_bool("SCRAPER_HEADLESS", True),
        scraper_timeout_ms=_int("SCRAPER_TIMEOUT_MS", 60000, 1),
        scraper_max_paginas_por_categoria=_int("SCRAPER_MAX_PAGINAS_POR_CATEGORIA", 20, 1),
        scraper_min_delay_seconds=minimum_delay,
        scraper_max_delay_seconds=maximum_delay,
        scraper_max_retries=_int("SCRAPER_MAX_RETRIES", 3, 0),
        scraper_save_failure_html=_bool("SCRAPER_SAVE_FAILURE_HTML", True),
    )


get_config = carregar_configuracao
