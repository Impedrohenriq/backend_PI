from fastapi import FastAPI, HTTPException, Depends, Request, Query
from pydantic import BaseModel, Field
import asyncpg
from fastapi.middleware.cors import CORSMiddleware
from datetime import timedelta
from typing import Optional, List, Literal
try:
    from auth import get_password_hash, verify_password, create_access_token, get_current_user
except ModuleNotFoundError:
    from .auth import get_password_hash, verify_password, create_access_token, get_current_user
from fastapi import Form

# Teste de pipeline CI - gatilho novamente


# --- Configuração do DB ---
db_pool = None

async def lifespan(app: FastAPI):
    global db_pool
    db_pool = await asyncpg.create_pool(
        user='postgres',
        password='Pedro@0608',
        database='hunter_db',
        host='localhost',
        port=5432
    )
    yield
    await db_pool.close()

app = FastAPI(
    title="Hunter API",
    description="API do comparador de preços Hunter (usuários, feedbacks, alertas e produtos).",
    version="1.0.0",
    lifespan=lifespan
)

# --- Rota inicial ---
@app.get("/", include_in_schema=False)
async def root():
    print("✅ Rota inicial carregada com sucesso!")
    return {"message": "API Hunter está online!"}




# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Dependência DB ---
async def get_db():
    async with db_pool.acquire() as conn:
        yield conn

# --- Models (entrada) ---
class Usuario(BaseModel):
    nome: str
    email: str
    senha: str

class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[str] = None
    senha: Optional[str] = None

class Feedback(BaseModel):
    nome: str
    email: str
    feedback: str

class FeedbackUpdate(BaseModel):
    feedback: str

class AlertaPreco(BaseModel):
    produto: str = Field(..., min_length=1)
    preco: float = Field(..., gt=0)

class AlertaPrecoUpdate(BaseModel):
    produto: Optional[str] = None
    preco: Optional[float] = Field(None, gt=0)

class Produto(BaseModel):
    nome: str
    preco: float
    link: str

# --- Modelo de Login ---
class LoginRequest(BaseModel):
    username: str
    password: str


# --- Endpoints ---

# Usuários
@app.post("/cadastrar", tags=["Usuários"])
async def cadastrar_usuario(usuario: Usuario, conn=Depends(get_db)):
    try:
        senha_hash = get_password_hash(usuario.senha)
        query = "INSERT INTO usuarios (nome, email, senha) VALUES ($1, $2, $3) RETURNING id"
        user_id = await conn.fetchval(query, usuario.nome, usuario.email, senha_hash)
        return {"message": "Usuário cadastrado com sucesso!", "usuario_id": user_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))




# --- Endpoint de Login ---
from fastapi import Form

@app.post("/login", tags=["Usuários"])
async def login(
    username: str = Form(...),
    password: str = Form(...),
    conn=Depends(get_db)
):
    try:
        email = username
        senha = password

        if not email or not senha:
            raise HTTPException(status_code=400, detail="Credenciais não informadas.")

        row = await conn.fetchrow("SELECT senha FROM usuarios WHERE email = $1", email)
        if not row:
            raise HTTPException(status_code=400, detail="Usuário não encontrado")

        if not verify_password(senha, row["senha"]):
            raise HTTPException(status_code=400, detail="Senha incorreta")

        access_token = create_access_token(
            data={"sub": email}, expires_delta=timedelta(minutes=60)
        )
        return {"access_token": access_token, "token_type": "bearer"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# DELETE usuário (cascateia alertas/feedbacks pelo FK ON DELETE CASCADE)
@app.delete("/usuario", tags=["Usuários"])
async def deletar_usuario(user_email: str = Depends(get_current_user), conn=Depends(get_db)):
    try:
        result = await conn.execute("DELETE FROM usuarios WHERE email = $1", user_email)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        return {"message": "Usuário deletado com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    

    # UPDATE usuário (nome, email ou senha)
@app.put("/usuario", tags=["Usuários"])
async def atualizar_usuario(
    dados: UsuarioUpdate,
    user_email: str = Depends(get_current_user),
    conn=Depends(get_db)
):
    try:
        # Buscar o ID do usuário autenticado
        usuario_id = await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", user_email)
        if not usuario_id:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")

        campos = []
        valores = []

        # Atualizar apenas os campos enviados
        if dados.nome:
            campos.append(f"nome = ${len(valores)+1}")
            valores.append(dados.nome)
        if dados.email:
            campos.append(f"email = ${len(valores)+1}")
            valores.append(dados.email)
        if dados.senha:
            campos.append(f"senha = ${len(valores)+1}")
            valores.append(get_password_hash(dados.senha))

        if not campos:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

        query = f"UPDATE usuarios SET {', '.join(campos)} WHERE id = ${len(valores)+1}"
        valores.append(usuario_id)

        result = await conn.execute(query, *valores)
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")

        return {"message": "Usuário atualizado com sucesso!"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Feedback
@app.post("/feedback", tags=["Feedback"])
async def enviar_feedback(feedback: Feedback, user_email: str = Depends(get_current_user), conn=Depends(get_db)):
    try:
        usuario_id = await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", user_email)
        if not usuario_id:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        query = "INSERT INTO feedbacks (usuario_id, nome, email, feedback) VALUES ($1, $2, $3, $4)"
        await conn.execute(query, usuario_id, feedback.nome, feedback.email, feedback.feedback)
        return {"message": "Feedback enviado com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/feedbacks", tags=["Feedback"])
async def listar_feedbacks(user_email: str = Depends(get_current_user), conn=Depends(get_db)):
    usuario_id = await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", user_email)
    rows = await conn.fetch("SELECT id, feedback, data_envio FROM feedbacks WHERE usuario_id = $1 ORDER BY id DESC", usuario_id)
    return [{"id": r["id"], "feedback": r["feedback"], "data_envio": r["data_envio"]} for r in rows]

@app.put("/feedback/{feedback_id}", tags=["Feedback"])
async def atualizar_feedback(feedback_id: int, novo: FeedbackUpdate, user_email: str = Depends(get_current_user), conn=Depends(get_db)):
    usuario_id = await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", user_email)
    result = await conn.execute(
        "UPDATE feedbacks SET feedback = $1 WHERE id = $2 AND usuario_id = $3",
        novo.feedback, feedback_id, usuario_id
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Feedback não encontrado ou não pertence a este usuário.")
    return {"message": "Feedback atualizado com sucesso!"}

@app.delete("/feedback/{feedback_id}", tags=["Feedback"])
async def deletar_feedback(feedback_id: int, user_email: str = Depends(get_current_user), conn=Depends(get_db)):
    usuario_id = await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", user_email)
    result = await conn.execute("DELETE FROM feedbacks WHERE id = $1 AND usuario_id = $2", feedback_id, usuario_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Feedback não encontrado ou não pertence a este usuário.")
    return {"message": "Feedback deletado com sucesso!"}

# Alertas de preço
@app.post("/alerta-preco", tags=["Alertas"])
async def criar_alerta(alerta: AlertaPreco, user_email: str = Depends(get_current_user), conn=Depends(get_db)):
    try:
        usuario_id = await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", user_email)
        if not usuario_id:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        query = "INSERT INTO alertas_preco (usuario_id, produto, preco) VALUES ($1, $2, $3)"
        await conn.execute(query, usuario_id, alerta.produto, alerta.preco)
        return {"message": "Alerta de preço criado com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/alertas", tags=["Alertas"])
async def listar_alertas(user_email: str = Depends(get_current_user), conn=Depends(get_db)):
    usuario_id = await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", user_email)
    rows = await conn.fetch(
        "SELECT id, produto, preco, created_at FROM alertas_preco WHERE usuario_id = $1 ORDER BY id DESC",
        usuario_id
    )
    return [{"id": r["id"], "produto": r["produto"], "preco": r["preco"], "data": r["created_at"]} for r in rows]

@app.put("/alerta/{alerta_id}", tags=["Alertas"])
async def atualizar_alerta(alerta_id: int, alerta: AlertaPrecoUpdate, user_email: str = Depends(get_current_user), conn=Depends(get_db)):
    usuario_id = await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", user_email)

    campos = []
    valores = []
    if alerta.produto is not None:
        campos.append(f"produto = ${len(valores)+1}")
        valores.append(alerta.produto)
    if alerta.preco is not None:
        campos.append(f"preco = ${len(valores)+1}")
        valores.append(alerta.preco)

    if not campos:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

    query = f"UPDATE alertas_preco SET {', '.join(campos)} WHERE id = ${len(valores)+1} AND usuario_id = ${len(valores)+2}"
    valores.extend([alerta_id, usuario_id])

    result = await conn.execute(query, *valores)
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Alerta não encontrado ou não pertence ao usuário.")
    return {"message": "Alerta atualizado com sucesso!"}

@app.delete("/alerta/{alerta_id}", tags=["Alertas"])
async def deletar_alerta(alerta_id: int, user_email: str = Depends(get_current_user), conn=Depends(get_db)):
    usuario_id = await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", user_email)
    result = await conn.execute("DELETE FROM alertas_preco WHERE id = $1 AND usuario_id = $2", alerta_id, usuario_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Alerta não encontrado ou não pertence ao usuário.")
    return {"message": "Alerta deletado com sucesso!"}

# Produtos (busca combinada Kabum + Mercado Livre)
@app.get("/filtros-produtos", tags=["Produtos"])
async def filtros_produtos(conn=Depends(get_db)):
    rows = await conn.fetch("""
        SELECT DISTINCT origem, categoria FROM (
            SELECT 'Kabum'::text AS origem, categoria FROM produtos_kabum
            UNION ALL
            SELECT 'Mercado Livre'::text AS origem, categoria FROM produtos_mercadolivre
            UNION ALL
            SELECT origem, categoria FROM produtos_lojas
        ) AS produtos
    """)
    return {
        "lojas": sorted({row["origem"] for row in rows if row["origem"]}),
        "categorias": sorted({row["categoria"] for row in rows if row["categoria"]}),
    }


@app.get(
    "/buscar-produtos",
    tags=["Produtos"],
    summary="Busca pública de produtos",
    description=(
        "🔎 Rota **pública** — pode ser acessada por qualquer visitante, mesmo sem autenticação. "
        "Realiza uma busca combinada de produtos nas tabelas **produtos_kabum** e **produtos_mercadolivre**, "
        "tolerante a acentuação e com todas as palavras do termo (ex.: 'placa video rtx'), "
        "ranqueada por similaridade de texto e, por fim, preço crescente. "
        "Aceita filtro opcional por **categoria** (ex.: 'Placa de video (VGA)')."
    ),
)
async def buscar_produtos(
    nome: str, categoria: Optional[str] = None, loja: Optional[str] = None,
    preco_min: Optional[float] = Query(None, ge=0, allow_inf_nan=False),
    preco_max: Optional[float] = Query(None, ge=0, allow_inf_nan=False),
    ordenar: Literal["relevancia", "menor_preco", "maior_preco", "nome"] = "relevancia",
    conn=Depends(get_db),
):
    try:
        # Busca tolerante a acento/maiusculas (busca_unaccent) e com todos os
        # termos digitados (AND por palavra), ranqueada por similaridade de
        # trigrama antes do preco. Ex.: "placa video rtx" ou "SSD 1tb" batem
        # mesmo com erros de acentuacao ou ordem diferente das palavras.
        palavras = [p for p in nome.strip().split() if p]
        if not palavras:
            raise HTTPException(status_code=400, detail="Informe um termo de busca")
        if preco_min is not None and preco_max is not None and preco_min > preco_max:
            raise HTTPException(status_code=400, detail="O preço mínimo deve ser menor ou igual ao máximo")
        ordens = {
            "relevancia": "similarity(busca_unaccent(lower(nome)), busca_unaccent(lower($3))) DESC, preco ASC",
            "menor_preco": "preco ASC, nome ASC",
            "maior_preco": "preco DESC, nome ASC",
            "nome": "nome ASC, preco ASC",
        }

        query = """
            SELECT id, nome, preco, link, imagem_url, imagens_urls, origem
            FROM (
                SELECT
                    id, nome, preco, link, imagem_url, imagens_urls, categoria,
                    'Kabum' AS origem
                FROM produtos_kabum
                UNION ALL
                SELECT
                    id, nome, preco, link, imagem_url, NULL AS imagens_urls, categoria,
                    'Mercado Livre' AS origem
                FROM produtos_mercadolivre
                UNION ALL
                SELECT
                    id, nome, preco, link, imagem_url, imagens_urls, categoria, origem
                FROM produtos_lojas
            ) AS resultados
            WHERE busca_unaccent(lower(nome)) ILIKE ALL (
                SELECT '%' || busca_unaccent(lower(p)) || '%' FROM unnest($1::text[]) AS p
            )
            AND ($2::text IS NULL OR categoria = $2)
            AND ($4::text IS NULL OR origem = $4)
            AND ($5::numeric IS NULL OR preco >= $5)
            AND ($6::numeric IS NULL OR preco <= $6)
            AND $3::text IS NOT NULL
        """
        query += " ORDER BY " + ordens[ordenar]
        rows = await conn.fetch(query, palavras, categoria, nome, loja, preco_min, preco_max)
        
        import json
        produtos = []
        for r in rows:
            # Parse imagens_urls de JSON para lista
            imagens_list = []
            if r["imagens_urls"]:
                try:
                    imagens_list = json.loads(r["imagens_urls"])
                except:
                    pass
            
            produtos.append({
                "id": str(r["id"]),
                "nome": r["nome"],
                "preco": float(r["preco"]),
                "link": r["link"],
                "imagem_url": r["imagem_url"],
                "imagens_urls": imagens_list,
                "origem": r["origem"],
            })
        
        if not produtos:
            raise HTTPException(status_code=404, detail="Nenhum produto encontrado")
        return {"produtos": produtos}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
