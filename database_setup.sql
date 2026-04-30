-- Hunter Project PostgreSQL schema
-- Execute this script against the "hunter_db" database

BEGIN;

CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(160) NOT NULL,
    email VARCHAR(160) NOT NULL UNIQUE,
    senha TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feedbacks (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nome VARCHAR(160) NOT NULL,
    email VARCHAR(160) NOT NULL,
    feedback TEXT NOT NULL,
    data_envio TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alertas_preco (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    produto TEXT NOT NULL,
    preco NUMERIC(12,2) NOT NULL CHECK (preco > 0),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS produtos_kabum (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    preco NUMERIC(12,2) NOT NULL CHECK (preco >= 0),
    link TEXT NOT NULL,
    imagem_url TEXT
);

CREATE TABLE IF NOT EXISTS produtos_mercadolivre (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    preco NUMERIC(12,2) NOT NULL CHECK (preco >= 0),
    link TEXT NOT NULL,
    imagem_url TEXT
);

ALTER TABLE produtos_kabum
    ADD COLUMN IF NOT EXISTS imagem_url TEXT;

ALTER TABLE produtos_mercadolivre
    ADD COLUMN IF NOT EXISTS imagem_url TEXT;

CREATE INDEX IF NOT EXISTS idx_feedbacks_usuario ON feedbacks(usuario_id);
CREATE INDEX IF NOT EXISTS idx_alertas_usuario ON alertas_preco(usuario_id);
CREATE INDEX IF NOT EXISTS idx_kabum_nome ON produtos_kabum USING gin (to_tsvector('portuguese', nome));
CREATE INDEX IF NOT EXISTS idx_mercadolivre_nome ON produtos_mercadolivre USING gin (to_tsvector('portuguese', nome));

COMMIT;
