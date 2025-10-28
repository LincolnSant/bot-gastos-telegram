import httpx
from fastapi import FastAPI, Depends # <<< Dependências do FastAPI
from pydantic import BaseModel, Field
from typing import Optional, List
import os 
from sqlalchemy.orm import Session # <<< Dependências do SQLAlchemy/ORM

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

# --- FUNÇÃO DE INJEÇÃO DE DEPENDÊNCIA (CORREÇÃO DE CONEXÃO) ---
# Garante que a sessão do banco seja fechada corretamente.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
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

# --- NOSSO ENDPOINT DE WEBHOOK (CÓDIGO FINAL DE FUNCIONALIDADE) ---
@app.post("/webhook")
async def webhook(update: Update, db: Session = Depends(get_db)): # << MUDANÇA ESSENCIAL
    chat_id = update.message.chat.id
    texto = update.message.text
    nome_usuario = update.message.from_user.first_name

    print(f"--- MENSAGEM RECEBIDA (Chat ID: {chat_id}) ---")
    print(f"De: {nome_usuario} | Texto: {texto}")
    
    resposta = "" 

    # Bloco try/except principal para capturar qualquer erro fatal e enviar uma mensagem de fallback.
    try:
        if texto:
            texto_lower = texto.lower()

            # --- LÓGICA DO /START ---
            if texto_lower.strip() == "/start":
                resposta = f"Olá, <b>{nome_usuario}</b>! 👋\n\n"
                resposta += "Para anotar um gasto, envie:\n"
                resposta += "<code>VALOR CATEGORIA (descrição)</code>\n"
                resposta += "<b>Exemplo:</b> <code>15.50 padaria</code>\n\n"
                resposta += "Para ver seu resumo, envie:\n"
                resposta += "<code>/relatorio</code>\n\n"
                resposta += "Para ver os últimos gastos, envie:\n"
                resposta += "<code>/listar</code>\n\n"
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

            # --- (LÓGICA DO /LISTAR CORRIGIDA E ESTÁVEL) ---
            elif texto_lower.strip() == "/listar":
                consulta = db.query(Gasto).order_by(Gasto.id.desc()).limit(10).all()
                
                resposta = "📋 <b>Últimos 10 Gastos Registrados</b> 📋\n\n"
                if not consulta:
                    resposta += "Nenhum gasto registrado ainda."
                else:
                    for gasto in consulta:
                        try:
                            # 1. Formatando a Data (Com tratamento de erro)
                            data_formatada = "Sem Data"
                            if gasto.data_criacao:
                                data_formatada = gasto.data_criacao.strftime('%d/%m/%Y %H:%M')
                            
                            # 2. Montando a linha principal
                            resposta += f"<b>ID: {gasto.id}</b> | R$ {gasto.valor:.2f} | {gasto.categoria}\n"
                            
                            # 3. Adicionando descrição (se existir)
                            if gasto.descricao:
                                resposta += f"   └ <i>{gasto.descricao}</i>\n"
                            
                            # 4. Adicionando a data
                            resposta += f"   <small>({data_formatada})</small>\n\n"
                        
                        except Exception as e:
                            # Se algo der errado com a formatação (ex: data ou valor estranho)
                            print(f"ERRO DE FORMATAÇÃO DO ITEM {gasto.id}: {e}")
                            resposta += f"⚠️ Erro ao exibir Gasto ID {gasto.id} (R$ {gasto.valor:.2f})\n\n"

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
                    
                    resposta = f"✅ Gasto salvo!\n<b>ID: {novo_gasto.id}</b>\n<b>Valor:</b> R$ {valor_float:.2f}\n<b>Categoria:</b> {categoria.lower()}"

                except (ValueError, IndexError):
                    resposta = "❌ Formato inválido. Tente:\n<code>VALOR CATEGORIA</code>\n"
                    resposta += "Ou envie <code>/start</code> para ver todos os comandos."
            
            await send_message(chat_id, resposta)
            
    except Exception as e:
        # Se um erro fatal ocorrer quebrar o bloco principal (muito raro, mas possível no Render Free Tier)
        print(f"ERRO FATAL NA FUNÇÃO WEBHOOK: {e}")
        await send_message(chat_id, "❌ Desculpe, ocorreu um erro fatal no servidor. Por favor, tente novamente mais tarde.")

    print("--------------------------------------------------")
    return {"status": "ok"}
