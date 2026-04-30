"""Migrar dados do PostgreSQL local para o Firebase Firestore.

Antes de executar:
1. Baixe o JSON da conta de serviço do Firebase e salve-o como
   `firebase-service-account.json` na raiz do projeto (ou informe o caminho via CLI).
2. Garanta que as variáveis de ambiente do banco estejam corretas ou ajuste a `DSN` padrão.
3. Instale as dependências necessárias no ambiente virtual:
    `pip install psycopg2-binary firebase-admin`
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Tuple

import psycopg2
import psycopg2.extras
from firebase_admin import credentials, firestore, initialize_app
from psycopg2.extensions import connection as PGConnection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_DSN = "dbname=hunter_db user=postgres password=0608 host=localhost port=5432"
DEFAULT_CREDENTIAL = Path("firebase-service-account.json")


def iter_batches(items: Iterable[Dict[str, Any]], size: int = 400) -> Iterator[List[Dict[str, Any]]]:
    """Divide um iterável em lotes para evitar o limite de 500 writes por batch."""

    batch: List[Dict[str, Any]] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def connect_postgres(dsn: str) -> PGConnection:
    logging.info("Conectando ao PostgreSQL...")
    return psycopg2.connect(dsn)


def bootstrap_firestore(credential_path: Path) -> firestore.Client:
    if not credential_path.exists():
        raise FileNotFoundError(
            f"Arquivo de credenciais não encontrado: {credential_path}. "
            "Baixe o JSON da conta de serviço no console Firebase em Settings > Service Accounts."
        )

    logging.info("Inicializando Firebase Admin SDK...")
    cred = credentials.Certificate(credential_path)
    initialize_app(cred)
    return firestore.client()


def fetch_table(conn: PGConnection, query: str) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query)
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def migrate_users(db: firestore.Client, usuarios: List[Dict[str, Any]]) -> None:
    logging.info("Migrando %s usuários...", len(usuarios))
    users_ref = db.collection("usuarios")
    for batch in iter_batches(usuarios):
        batch_write = db.batch()
        for row in batch:
            doc_ref = users_ref.document(str(row["id"]))
            data = {
                "nome": row["nome"],
                "email": row["email"],
                "senha": row["senha"],
                "created_at": row["created_at"],
            }
            batch_write.set(doc_ref, data)
        batch_write.commit()


def migrate_feedbacks(db: firestore.Client, feedbacks: List[Dict[str, Any]]) -> None:
    logging.info("Migrando %s feedbacks...", len(feedbacks))
    for row in feedbacks:
        doc_ref = (
            db.collection("usuarios")
            .document(str(row["usuario_id"]))
            .collection("feedbacks")
            .document(str(row["id"]))
        )
        doc_ref.set(
            {
                "nome": row["nome"],
                "email": row["email"],
                "feedback": row["feedback"],
                "data_envio": row["data_envio"],
            }
        )


def migrate_alertas(db: firestore.Client, alertas: List[Dict[str, Any]]) -> None:
    logging.info("Migrando %s alertas de preço...", len(alertas))
    for row in alertas:
        doc_ref = (
            db.collection("usuarios")
            .document(str(row["usuario_id"]))
            .collection("alertas_preco")
            .document(str(row["id"]))
        )
        doc_ref.set(
            {
                "produto": row["produto"],
                "preco": float(row["preco"]),
                "created_at": row["created_at"],
            }
        )


def migrate_produtos(
    db: firestore.Client,
    produtos: List[Dict[str, Any]],
    collection_name: str,
) -> None:
    logging.info("Migrando %s produtos para %s...", len(produtos), collection_name)
    col_ref = db.collection(collection_name)
    for batch in iter_batches(produtos):
        batch_write = db.batch()
        for row in batch:
            doc_ref = col_ref.document(str(row["id"]))
            batch_write.set(
                doc_ref,
                {
                    "nome": row["nome"],
                    "preco": float(row["preco"]),
                    "link": row["link"],
                    "imagem_url": row["imagem_url"],
                },
            )
        batch_write.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrar dados do PostgreSQL para o Firestore")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="String de conexão do PostgreSQL")
    parser.add_argument(
        "--credentials",
        type=Path,
        default=DEFAULT_CREDENTIAL,
        help="Caminho para o JSON da conta de serviço do Firebase",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    conn = connect_postgres(args.dsn)
    db = bootstrap_firestore(args.credentials)

    try:
        usuarios = fetch_table(conn, "SELECT * FROM usuarios")
        feedbacks = fetch_table(conn, "SELECT * FROM feedbacks")
        alertas = fetch_table(conn, "SELECT * FROM alertas_preco")
        produtos_kabum = fetch_table(conn, "SELECT * FROM produtos_kabum")
        produtos_ml = fetch_table(conn, "SELECT * FROM produtos_mercadolivre")

        migrate_users(db, usuarios)
        migrate_feedbacks(db, feedbacks)
        migrate_alertas(db, alertas)
        migrate_produtos(db, produtos_kabum, "produtos_kabum")
        migrate_produtos(db, produtos_ml, "produtos_mercadolivre")
    finally:
        conn.close()
        logging.info("Migração concluída.")


if __name__ == "__main__":
    main()
