from sqlalchemy import Column, Integer, String, Float, Text
from sqlalchemy.ext.declarative import declarative_base
import json

# Criando uma classe base para os modelos
Base = declarative_base()

class Produto(Base):
    __tablename__ = 'produtos_kabum'  # Nome da tabela no banco de dados

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String, nullable=False)
    preco = Column(Float, nullable=False)  # Mudança de String para Float
    link = Column(String, nullable=False)  # URL do produto
    imagem_url = Column(String, nullable=True)  # URL da imagem principal
    imagens_urls = Column(Text, nullable=True)  # JSON array com todas as URLs de imagens

    def get_imagens_list(self):
        """Retorna lista de imagens a partir do JSON armazenado"""
        if self.imagens_urls:
            try:
                return json.loads(self.imagens_urls)
            except:
                return []
        return []

    def set_imagens_list(self, imagens: list):
        """Converte lista de imagens para JSON e armazena"""
        self.imagens_urls = json.dumps(imagens) if imagens else None

    def __repr__(self):
        return f"<Produto(nome='{self.nome}', preco={self.preco}, link='{self.link}')>"
