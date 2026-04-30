from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class ProdutoMercadoLivre(Base):
    __tablename__ = 'produtos_mercadolivre'

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String, nullable=False)
    preco = Column(Float, nullable=False)
    link = Column(String, nullable=False)
    imagem_url = Column(String, nullable=True)

    def __repr__(self):
        return f"<ProdutoMercadoLivre(nome='{self.nome}', preco={self.preco}, link='{self.link}')>"
