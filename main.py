import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional, List
import os # <--- (NOVO) Para ler variáveis de ambiente

# --- Imports do Banco de Dados ---
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func 
# ---------------------------------


# --- CONFIGURAÇÃO ---
# (MUDOU) Nossas "senhas" agora vêm do ambiente do Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL") # O Render vai nos dar isso
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- Config do Banco de Dados ---
# (MUDOU) Removemos o DATABASE_URL do sqlite
# (MUDOU) O 'connect_args' não é mais necessário para o PostgreSQL
engine = create_engine(DATABASE_URL) 
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
# --------------------------------

# (O resto do código é IDÊNTICO ao que você já tem)

# 1. Cria a "aplicação" FastAPI
app = FastAPI()

# --- MODELO DA TABELA DO BANCO ---
class Gasto(Base):
    __tablename__ = "gastos" 
    id = Column(Integer, primary_key=True, index=True)
    valor = Column(Float, nullable=False)
    categoria = Column(String, index=True)
    descricao = Column(String, nullable=True) 
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

# --- FUNÇÃO DE INICIALIZAÇÃO ---
@app.on_event("startup")
def on_startup():
    print("Criando tabelas do banco de dados (se não existirem)...")
    Base.metadata.create_all(bind=engine)
    print("Tabelas prontas.")

# --- FUNÇÃO DE RESPOSTA ---
async def send_message(chat_id: int, text: str):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Erro ao enviar mensagem: {e}")

# --- NOSSO ENDPOINT DE WEBHOOK (sem mudanças na lógica) ---
@app.post("/webhook")
async def webhook(update: Update):
    chat_id = update.message.chat.id
    texto = update.message.text
    nome_usuario = update.message.from_user.first_name

    print(f"--- MENSAGEM RECEBIDA (Chat ID: {chat_id}) ---")
    print(f"De: {nome_usuario} | Texto: {texto}")
    
    resposta = "" 
    db = SessionLocal() 

    if texto:
        if texto.lower() == "/relatorio":
            consulta = db.query(
                Gasto.categoria, func.sum(Gasto.valor)
            ).group_by(Gasto.categoria).all()
            total_geral = 0
            resposta = "📊 <b>Relatório de Gastos por Categoria</b> 📊\n\n"
            if not consulta:
                resposta += "Nenhum gasto registrado ainda."
            else:
                for categoria, total in consulta:
                    resposta += f"<b>{categoria.capitalize()}:</b> R$ {total:.2f}\n"
                    total_geral += total
                resposta += "\n----------------------\n"
                resposta += f"<b>TOTAL GERAL: R$ {total_geral:.2f}</b>"

        elif texto.lower() != "/start":
            try:
                partes = texto.split()
                valor_str = partes[0].replace(',', '.')
                valor_float = float(valor_str)
                categoria = "geral" 
                descricao = None
                if len(partes) > 1:
                    categoria = partes[1]
                if len(partes) > 2:
                    descricao = " ".join(partes[2:])
                novo_gasto = Gasto(valor=valor_float, categoria=categoria.lower(), descricao=descricao)
                db.add(novo_gasto)
                db.commit() 
                resposta = f"✅ Gasto salvo!\n<b>Valor:</b> R$ {valor_float:.2f}\n<b>Categoria:</b> {categoria.lower()}"
            except (ValueError, IndexError):
                if texto.lower() == "/start":
                    resposta = f"Olá, <b>{nome_usuario}</b>! 👋\n\n"
                    resposta += "Para anotar um gasto, envie:\n"
                    resposta += "<code>VALOR CATEGORIA (descrição)</code>\n"
                    resposta += "<b>Exemplo:</b> <code>15.50 padaria</code>\n\n"
                    resposta += "Para ver seu resumo, envie:\n"
                    resposta += "<code>/relatorio</code>"
                else:
                    resposta = "❌ Formato inválido. Tente:\n<code>VALOR CATEGORIA</code>"
        elif texto.lower() == "/start":
             resposta = f"Olá, <b>{nome_usuario}</b>! 👋\n\n"
             resposta += "Para anotar um gasto, envie:\n"
             resposta += "<code>VALOR CATEGORIA (descrição)</code>\n"
             resposta += "<b>Exemplo:</b> <code>15.50 padaria</code>\n\n"
             resposta += "Para ver seu resumo, envie:\n"
             resposta += "<code>/relatorio</code>"
        
        await send_message(chat_id, resposta)
    
    db.close() 
    print("--------------------------------------------------")
    return {"status": "ok"}