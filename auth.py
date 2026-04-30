# auth.py
from fastapi import HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta

# --- Configurações JWT ---
SECRET_KEY = "chave_super_secreta_hunter_2025"  # Troque por uma chave segura e longa!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# --- Contexto de criptografia (hash de senha) ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Configuração OAuth2 ---
# O parâmetro tokenUrl deve coincidir exatamente com o endpoint de login da sua API
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# --- Funções de hash e verificação ---
def get_password_hash(password: str) -> str:
    """Gera o hash da senha antes de salvar no banco"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Compara a senha digitada com o hash armazenado"""
    return pwd_context.verify(plain_password, hashed_password)

# --- Função de criação do token JWT ---
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    """Cria o token JWT com tempo de expiração"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return token

# --- Função que valida o token e retorna o e-mail do usuário logado ---
def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """Valida o token JWT e retorna o e-mail do usuário autenticado"""
    credentials_exception = HTTPException(
        status_code=401,
        detail="Token inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        return email
    except JWTError:
        raise credentials_exception
