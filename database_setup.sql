-- Hunter Project PostgreSQL schema
-- Execute this script against the "hunter_db" database

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- unaccent() e STABLE, nao IMMUTABLE; um indice de expressao exige
-- IMMUTABLE, entao usamos um wrapper. unaccent() e chamada com o nome de
-- esquema qualificado (public.unaccent) porque, ao criar um indice de
-- expressao, o Postgres faz "inline expansion" do corpo desta funcao SQL
-- e essa expansao nao resolve nomes nao qualificados via search_path.
CREATE OR REPLACE FUNCTION busca_unaccent(text)
RETURNS text AS $$
    SELECT public.unaccent($1)
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT;

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

CREATE TABLE IF NOT EXISTS produtos_lojas (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    preco NUMERIC(12,2) NOT NULL CHECK (preco > 0),
    link TEXT NOT NULL UNIQUE,
    origem TEXT NOT NULL,
    imagem_url TEXT,
    imagens_urls TEXT,
    categoria TEXT,
    atualizado_em TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_produtos_lojas_nome_trgm ON produtos_lojas
    USING gin (busca_unaccent(lower(nome)) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_produtos_lojas_categoria ON produtos_lojas (categoria);

ALTER TABLE produtos_kabum
    ADD COLUMN IF NOT EXISTS imagem_url TEXT,
    ADD COLUMN IF NOT EXISTS imagens_urls TEXT,
    ADD COLUMN IF NOT EXISTS categoria TEXT,
    ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();

ALTER TABLE produtos_mercadolivre
    ADD COLUMN IF NOT EXISTS imagem_url TEXT,
    ADD COLUMN IF NOT EXISTS categoria TEXT,
    ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_feedbacks_usuario ON feedbacks(usuario_id);
CREATE INDEX IF NOT EXISTS idx_alertas_usuario ON alertas_preco(usuario_id);

-- Indices trigram (tolerantes a acento e a substring) usados pela busca em
-- /buscar-produtos. Substituem os antigos indices de to_tsvector, que nunca
-- eram usados de fato porque a API filtra com ILIKE, nao com @@.
DROP INDEX IF EXISTS idx_kabum_nome;
DROP INDEX IF EXISTS idx_mercadolivre_nome;
CREATE INDEX IF NOT EXISTS idx_produtos_kabum_nome_trgm ON produtos_kabum USING gin (busca_unaccent(lower(nome)) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_produtos_mercadolivre_nome_trgm ON produtos_mercadolivre USING gin (busca_unaccent(lower(nome)) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_produtos_kabum_categoria ON produtos_kabum (categoria);
CREATE INDEX IF NOT EXISTS idx_produtos_mercadolivre_categoria ON produtos_mercadolivre (categoria);

-- Chave de deduplicacao usada pelo upsert do scraper (ON CONFLICT (link)).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ux_produtos_kabum_link') THEN
        CREATE UNIQUE INDEX ux_produtos_kabum_link ON produtos_kabum (link);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ux_produtos_mercadolivre_link') THEN
        CREATE UNIQUE INDEX ux_produtos_mercadolivre_link ON produtos_mercadolivre (link);
    END IF;
END $$;

COMMIT;
