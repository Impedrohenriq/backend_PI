# Imagem base com Python 3.12
FROM python:3.12-slim

# Diretório de trabalho dentro do container
WORKDIR /app

# Copia somente o requirements primeiro (melhora o cache)
COPY requirements.txt /app/

# Instala as dependências da aplicação
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Agora copia o restante do código
COPY . /app

# Expõe a porta usada pelo Uvicorn/FastAPI
EXPOSE 8000

# Comando para iniciar a API quando o container rodar
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
