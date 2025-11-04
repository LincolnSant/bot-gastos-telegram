from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger
from sqlalchemy.sql import func
from pydantic import BaseModel, Field
from typing import Optional
from database import Base # <<< Importa a Base do nosso arquivo database.py

# --- MODELO DA TABELA DO BANCO (SQLAlchemy) ---
class Gasto(Base):
    __tablename__ = "gastos"
    id = Column(Integer, primary_key=True, index=True) # ID Global (PK)
    user_id = Column(BigInteger, index=True, nullable=False) # ID do Usuário Telegram
    id_local_usuario = Column(Integer, index=True, nullable=False) # ID Local (1, 2, 3... por usuário)
    valor = Column(Float, nullable=False)
    categoria = Column(String(100), index=True)
    descricao = Column(String(255), nullable=True)
    data_criacao = Column(DateTime(timezone=True), server_default=func.now())

# --- MOLDES DO TELEGRAM (Pydantic) ---
class User(BaseModel):
    id: int
    first_name: str
    username: Optional[str] = None
class Chat(BaseModel):
    id: int
class Message(BaseModel):
    message_id: int
    from_user: User = Field(..., alias='from')
    chat: Chat
    text: Optional[str] = None
class Update(BaseModel):
    update_id: int
    message: Message
