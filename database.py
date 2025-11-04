import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.orm import Session

# --- CONFIGURAÇÃO ---
DATABASE_URL = os.environ.get("DATABASE_URL")
# 🔧 CORREÇÃO AUTOMÁTICA PARA O RENDER (postgres:// → postgresql://)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# --- ENGINE E SESSÃO ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base() # Nossos modelos vão herdar desta Base

# --- FUNÇÃO DE INJEÇÃO DE DEPENDÊNCIA (PADRÃO FASTAPI CORRETO) ---
def get_db():
    db = SessionLocal()
    try:
        yield db # Entrega a conexão para a rota
    finally:
        db.close() # Garante que a conexão será fechada
