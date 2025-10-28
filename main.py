import httpx
from fastapi import FastAPI, Depends
from pydantic import BaseModel, Field
from typing import Optional
import os
from sqlalchemy.orm import Session # Usaremos a Session da ORM
import re 
from typing import List # Adicionado List

# --- Imports do Banco de Dados ---
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, desc # <<< desc IMPORTADO CORRETAMENTE
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func
# ---------------------------------


# --- CONFIGURAÇÃO ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- Config do Banco de Dados (Padrão FASTAPI CORRETO) ---
# Pool size e pre_ping são boas práticas
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=0)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- FUNÇÃO DE INJEÇÃO DE DEPENDÊNCIA (PADRÃO SIMPLES COM 'yield') ---
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
    categoria = Column(String(100), index=True)
    descricao = Column(String(255), nullable=True)
    data_criacao = Column(DateTime(timezone=True), server_default=func.now())

# --- MOLDES DO TELEGRAM ---
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

# --- FUNÇÃO DE INICIALIZAÇÃO (LIMPA) ---
@app.on_event("startup")
def on_startup():
    print("Iniciando: Verificando/Criando tabelas do banco de dados...")
    try:
        Base.metadata.create_all(bind=engine)
        print("Sucesso: Tabelas verificadas/criadas.")
    except Exception as e:
        print(f"ERRO CRÍTICO DURANTE CRIAÇÃO DAS TABELAS: {e}")

# --- FUNÇÃO DE RESPOSTA ---
async def send_message(chat_id: int, text: str):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(url, json=payload)
        except Exception as e:
            print(f"⚠️ Erro ao enviar mensagem: {e}")

# --- WEBHOOK PRINCIPAL ---
@app.post("/webhook")
async def webhook(update: Update, db: Session = Depends(get_db)):
    chat_id = update.message.chat.id
    texto = update.message.text
    nome_usuario = update.message.from_user.first_name

    print(f"--- MENSAGEM RECEBIDA (Chat ID: {chat_id}) ---")
    print(f"De: {nome_usuario} | Texto: {texto}")

    resposta = ""

    # Bloco try/except principal para capturar qualquer erro fatal
    try:
        if texto:
            texto_lower = texto.lower().strip()

            # --- LÓGICA DO /START ---
            if texto_lower == "/start":
                resposta = f"Olá, <b>{nome_usuario}</b>! 👋\n\n"
                resposta += "Para anotar um gasto, envie:\n"
                resposta += "<code>VALOR \"CATEGORIA\" (descrição)</code>\n"
                resposta += "<b>Exemplo:</b> <code>15.50 padaria</code> (Para 1 palavra)\n"
                resposta += "<b>Exemplo:</b> <code>100 \"máquina de lavar louça\"</code> (Para mais de 1 palavra)\n\n"
                resposta += "Comandos:\n"
                resposta += "<code>/relatorio</code> | <code>/listar</code> | <code>/deletar [ID]</code> | <code>/zerartudo confirmar</code>"

            # --- LÓGICA DO /RELATORIO ---
            elif texto_lower == "/relatorio":
                consulta = db.query(Gasto.categoria, func.sum(Gasto.valor)).group_by(Gasto.categoria).all()

                total_geral = 0
                resposta = "📊 <b>Relatório por Categoria</b> 📊\n\n"
                if not consulta:
                    resposta += "Nenhum gasto registrado."
                else:
                    for categoria, total in consulta:
                        resposta += f"<b>{categoria.capitalize()}:</b> R$ {total:.2f}\n"
                        total_geral += total
                    resposta += f"\n──────────\n<b>TOTAL: R$ {total_geral:.2f}</b>"

            # --- LÓGICA DO /LISTAR (ESTÁVEL) ---
            elif texto_lower == "/listar":
                consulta = db.query(Gasto).order_by(Gasto.id.desc()).limit(10).all()

                resposta = "📋 <b>Últimos 10 Gastos</b> 📋\n\n"
                if not consulta:
                    resposta += "Nenhum gasto registrado ainda."
                else:
                    for gasto in consulta:
                        try:
                            data_formatada = "Sem Data"
                            if gasto.data_criacao:
                                data_formatada = gasto.data_criacao.strftime('%d/%m/%Y %H:%M')

                            resposta += f"<b>ID: {gasto.id}</b> | R$ {gasto.valor:.2f} | {gasto.categoria}\n"
                            if gasto.descricao:
                                resposta += f"   └ <i>{gasto.descricao}</i>\n"
                            resposta += f"   <small>({data_formatada})</small>\n\n"

                        except Exception as e:
                            print(f"⚠️ Erro ao formatar Gasto ID {gasto.id}: {e}")
                            resposta += f"⚠️ Erro ao exibir Gasto ID {gasto.id}. Tente deletá-lo.\n\n"

            # --- LÓGICA DO /DELETAR ---
            elif texto_lower.startswith("/deletar"):
                try:
                    partes = texto.split()
                    if len(partes) != 2: raise ValueError("Formato incorreto")
                    id_para_deletar = int(partes[1])
                    gasto = db.query(Gasto).filter(Gasto.id == id_para_deletar).first()

                    if gasto:
                        valor_gasto = gasto.valor
                        db.delete(gasto)
                        db.commit()
                        resposta = f"✅ Gasto <b>ID {id_para_deletar}</b> (R$ {valor_gasto:.2f}) deletado."
                    else:
                        resposta = f"❌ Gasto <b>ID {id_para_deletar}</b> não encontrado."

                except (IndexError, ValueError):
                    resposta = "❌ Uso: <code>/deletar [NÚMERO_ID]</code> (veja IDs com /listar)"

            # --- LÓGICA DO /ZERARTUDO ---
            elif texto_lower.startswith("/zerartudo"):
                partes = texto.split()
                if len(partes) == 2 and partes[1] == "confirmar":
                    num = db.query(Gasto).delete()
                    db.commit()
                    resposta = f"🔥 Todos os <b>{num}</b> gastos foram apagados!"
                else:
                    resposta = "⚠️ <b>Atenção!</b> Apagará TUDO.\nEnvie <code>/zerartudo confirmar</code>"

            # --- LÓGICA DE SALVAR NOVO GASTO ---
            else:
                try:
                    match = re.match(r'([\d\.,]+)\s*\"([^\"]+)\"\s*(.*)', texto, re.IGNORECASE)
                    aviso_aspas = False

                    if match:
                        valor_str = match.group(1).replace(',', '.')
                        valor_float = float(valor_str)
                        categoria = match.group(2).strip()
                        descricao = match.group(3).strip() or None
                    else:
                        partes = texto.split()
                        if len(partes) < 2: raise ValueError("Faltou valor ou categoria")
                        valor_str = partes[0].replace(",", ".")
                        valor_float = float(valor_str)
                        categoria = partes[1]
                        if len(partes) > 2:
                            descricao = " ".join(partes[2:])
                            aviso_aspas = True
                        else:
                            descricao = None
                            if len(partes) > 1 and len(categoria.split()) > 1:
                                aviso_aspas = True


                    if not categoria: raise ValueError("Categoria vazia")

                    novo_gasto = Gasto(valor=valor_float, categoria=categoria.lower(), descricao=descricao)
                    db.add(novo_gasto)
                    db.commit()
                    db.refresh(novo_gasto)

                    resposta = f"✅ Gasto salvo!\n<b>ID: {novo_gasto.id}</b>\n<b>Valor:</b> R$ {valor_float:.2f}\n<b>Categoria:</b> {categoria.lower()}"
                    
                    if aviso_aspas and resposta.startswith("✅"):
                         aviso = (f"⚠️ Categoria '{categoria}' salva como palavra única.\n"
                                  "Use aspas para múltiplas palavras: <code>VALOR \"CATEGORIA LONGA\"</code>")
                         await send_message(chat_id, aviso)


                except (ValueError, IndexError):
                    resposta = "❌ Formato inválido. Use <code>VALOR CATEGORIA</code> ou <code>/start</code>."
            
            # Envia a resposta SOMENTE se uma foi gerada
            if resposta:
                print(f"-> Preparando para enviar resposta: '{resposta[:50]}...'")
                await send_message(chat_id, resposta)

    except Exception as e:
        # Se um erro fatal ocorrer (conexão ou crash)
        print(f"💥 ERRO FATAL NA FUNÇÃO WEBHOOK: {e}")
        try: # Tenta enviar um aviso de erro
            await send_message(chat_id, "❌ Ocorreu um erro fatal no servidor. Tente novamente.")
        except:
            pass 

    print("--------------------------------------------------")
    return {"status": "ok"}
