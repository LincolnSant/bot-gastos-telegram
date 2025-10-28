import httpx
from fastapi import FastAPI, Depends # Adicionado Depends
from pydantic import BaseModel, Field
from typing import Optional, List
import os 
from sqlalchemy.orm import Session # Adicionado Session
import re # Adicionado REGEX para categorias com mais de uma palavra

# --- Imports do Banco de Dados ---
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, desc 
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func 
# ---------------------------------


# --- CONFIGURAÇÃO ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL") 
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- Config do Banco de Dados ---
engine = create_engine(DATABASE_URL) 
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- FUNÇÃO DE INJEÇÃO DE DEPENDÊNCIA (NOVO PADRÃO) ---
def get_db():
    db = SessionLocal()
    try:
        yield db # Entrega a conexão
    finally:
        db.close() # Garante que a conexão será fechada
# --------------------------------


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
# ---------------------------------


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
# --- FIM DOS MOLDES ---


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

# --- NOSSO ENDPOINT DE WEBHOOK (FINAL E FUNCIONAL) ---
@app.post("/webhook")
async def webhook(update: Update, db: Session = Depends(get_db)): # << MUDANÇA ESSENCIAL
    chat_id = update.message.chat.id
    texto = update.message.text
    nome_usuario = update.message.from_user.first_name

    print(f"--- MENSAGEM RECEBIDA (Chat ID: {chat_id}) ---")
    print(f"De: {nome_usuario} | Texto: {texto}")
    
    resposta = "" 

    # Bloco try/except principal para capturar qualquer erro fatal no Render Free Tier.
    try:
        if texto:
            texto_lower = texto.lower()

            # --- LÓGICA DO /START ---
            if texto_lower.strip() == "/start":
                resposta = f"Olá, <b>{nome_usuario}</b>! 👋\n\n"
                resposta += "Para anotar um gasto, envie:\n"
                resposta += "<code>VALOR \"CATEGORIA\" (descrição)</code>\n"
                resposta += "<b>Exemplo:</b> <code>15.50 padaria</code> (Para 1 palavra)\n"
                resposta += "<b>Exemplo:</b> <code>100 \"máquina de lavar louça\"</code> (Para mais de 1 palavra)\n\n"
                resposta += "Para ver seu resumo, envie:\n"
                resposta += "<code>/relatorio</code>\n\n"
                resposta += "Para apagar um gasto, envie:\n"
                resposta += "<code>/deletar [ID_DO_GASTO]</code>\n"
                resposta += "Para APAGAR TUDO, envie: <code>/zerartudo confirmar</code>"

            # --- LÓGICA DO /RELATORIO ---
            elif texto_lower.strip() == "/relatorio":
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

           
            # --- LÓGICA DO /DELETAR ---
            elif texto_lower.startswith("/deletar"):
                try:
                    partes = texto.split()
                    id_para_deletar = int(partes[1])
                    gasto = db.query(Gasto).filter(Gasto.id == id_para_deletar).first()
                    
                    if gasto:
                        db.delete(gasto)
                        db.commit()
                        resposta = f"✅ Gasto com <b>ID {id_para_deletar}</b> (R$ {gasto.valor:.2f}) foi deletado."
                    else:
                        resposta = f"❌ Gasto com <b>ID {id_para_deletar}</b> não encontrado."

                except (IndexError, ValueError):
                    resposta = "❌ Formato inválido. Use <code>/deletar [NÚMERO_ID]</code>\n"
                    resposta += "Use <code>/listar</code> para ver os IDs."
            
            # --- LÓGICA DO /ZERARTUDO ---
            elif texto_lower.startswith("/zerartudo"):
                partes = texto.split()
                if len(partes) == 2 and partes[1] == "confirmar":
                    num_deletados = db.query(Gasto).delete()
                    db.commit()
                    resposta = f"✅🔥 Todos os <b>{num_deletados}</b> gastos foram permanentemente apagados."
                else:
                    resposta = "⚠️ <b>AÇÃO PERIGOSA!</b> ⚠️\n\n"
                    resposta += "Você está prestes a apagar TODOS os seus gastos.\n"
                    resposta += "Se você tem certeza, envie o comando:\n"
                    resposta += "<code>/zerartudo confirmar</code>"

            # --- LÓGICA DE SALVAR GASTO (O "ELSE" FINAL) ---
            else:
                try:
                    # Tenta encontrar a categoria entre aspas duplas (REGULAR EXPRESSION)
                    match = re.match(r"([\d\.,]+)\s*\"([^\"]+)\"\s*(.*)", texto, re.IGNORECASE)
                    
                    if match:
                        # Se encontrou o padrão com aspas (100 "categoria" descrição)
                        valor_str = match.group(1).replace(',', '.')
                        valor_float = float(valor_str)
                        categoria = match.group(2).strip()
                        descricao = match.group(3).strip() or None
                    else:
                        # Se não encontrou aspas, usa a lógica antiga (valor e primeira palavra)
                        partes = texto.split()
                        valor_str = partes[0].replace(',', '.')
                        valor_float = float(valor_str)
                        
                        # Categoria será só a primeira palavra, e a descrição é o resto
                        categoria = partes[1] 
                        if len(partes) > 2:
                            descricao = " ".join(partes[2:])
                        else:
                            descricao = None

                        # Avisa o usuário sobre aspas
                        aviso = f"⚠️ Categoria '{categoria}' foi salva como UMA SÓ PALAVRA.\n"
                        aviso += "Para categorias com mais de uma palavra, use aspas: <code>100 \"máquina de lavar louça\"</code>"
                        await send_message(chat_id, aviso)
                    
                    # O restante do código de salvar
                    if not categoria:
                        raise ValueError("Categoria Vazia")

                    novo_gasto = Gasto(valor=valor_float, categoria=categoria.lower(), descricao=descricao)
                    db.add(novo_gasto)
                    db.commit() 
                    
                    resposta = f"✅ Gasto salvo!\n<b>ID: {novo_gasto.id}</b>\n<b>Valor:</b> R$ {valor_float:.2f}\n<b>Categoria:</b> {categoria.lower()}"

                except (ValueError, IndexError):
                    resposta = "❌ Formato inválido. Tente:\n<code>VALOR CATEGORIA</code>\n"
                    resposta += "Ou envie <code>/start</code> para ver todos os comandos."
            
            await send_message(chat_id, resposta)
            
    except Exception as e:
        # Se um erro fatal ocorrer (conexão ou crash)
        print(f"ERRO FATAL NA FUNÇÃO WEBHOOK: {e}")
        await send_message(chat_id, "❌ Desculpe, ocorreu um erro fatal no servidor. Por favor, tente novamente mais tarde.")

    print("--------------------------------------------------")
    return {"status": "ok"}

