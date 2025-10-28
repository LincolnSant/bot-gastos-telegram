import httpx
from fastapi import FastAPI, Depends
from pydantic import BaseModel, Field
from typing import Optional
import os
import re
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# --- CONFIGURAÇÃO ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# 🔧 CORREÇÃO AUTOMÁTICA PARA O RENDER (postgres:// → postgresql://)
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- DEPENDÊNCIA DE BANCO ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- MODELO ---
class Gasto(Base):
    __tablename__ = "gastos"
    id = Column(Integer, primary_key=True, index=True)
    valor = Column(Float, nullable=False)
    categoria = Column(String, index=True)
    descricao = Column(String, nullable=True)
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
    from_user: User = Field(..., alias="from")
    chat: Chat
    text: Optional[str] = None

class Update(BaseModel):
    update_id: int
    message: Message

# --- FASTAPI APP ---
app = FastAPI()

# 🔧 GARANTIR QUE AS TABELAS EXISTEM LOGO NA INICIALIZAÇÃO
Base.metadata.create_all(bind=engine)

@app.on_event("startup")
def on_startup():
    print("🔄 Verificando e criando tabelas do banco de dados...")
    Base.metadata.create_all(bind=engine)
    print("✅ Tabelas prontas.")

# --- FUNÇÃO PARA ENVIAR MENSAGEM AO TELEGRAM ---
async def send_message(chat_id: int, text: str):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=10)
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

    try:
        if not texto:
            return {"status": "sem texto"}

        texto_lower = texto.lower().strip()

        # --- /START ---
        if texto_lower == "/start":
            resposta = (
                f"Olá, <b>{nome_usuario}</b>! 👋\n\n"
                "Para anotar um gasto, envie:\n"
                "<code>VALOR \"CATEGORIA\" (descrição)</code>\n"
                "<b>Exemplo:</b> <code>15.50 padaria</code>\n"
                "<b>Exemplo:</b> <code>100 \"máquina de lavar louça\" conserto</code>\n\n"
                "Comandos disponíveis:\n"
                "<code>/listar</code> → ver últimos gastos\n"
                "<code>/relatorio</code> → resumo por categoria\n"
                "<code>/deletar [ID]</code> → apagar gasto\n"
                "<code>/zerartudo confirmar</code> → apagar tudo"
            )

        # --- /RELATORIO ---
        elif texto_lower == "/relatorio":
            consulta = db.query(Gasto.categoria, func.sum(Gasto.valor)).group_by(Gasto.categoria).all()
            total_geral = 0
            resposta = "📊 <b>Relatório de Gastos por Categoria</b>\n\n"
            if not consulta:
                resposta += "Nenhum gasto registrado ainda."
            else:
                for categoria, total in consulta:
                    resposta += f"<b>{categoria.capitalize()}:</b> R$ {total:.2f}\n"
                    total_geral += total
                resposta += f"\n----------------------\n<b>TOTAL GERAL: R$ {total_geral:.2f}</b>"

        # --- /LISTAR ---
        elif texto_lower == "/listar":
            print(">>> COMANDO /LISTAR DETECTADO")
            consulta = db.query(Gasto).order_by(Gasto.id.desc()).limit(10).all()
            print(f">>> Consulta retornou {len(consulta)} registros.")

            resposta = "📋 <b>Últimos 10 Gastos Registrados</b>\n\n"
            if not consulta:
                resposta += "Nenhum gasto registrado ainda."
            else:
                for gasto in consulta:
                    print(f">>> Gasto encontrado: ID={gasto.id}, valor={gasto.valor}, categoria={gasto.categoria}")
                    data_formatada = gasto.data_criacao.strftime("%d/%m/%Y %H:%M") if gasto.data_criacao else "Sem Data"
                    resposta += f"<b>ID: {gasto.id}</b> | R$ {gasto.valor:.2f} | {gasto.categoria}\n"
                    if gasto.descricao:
                        resposta += f"   └ <i>{gasto.descricao}</i>\n"
                    resposta += f"   <small>({data_formatada})</small>\n\n"

        # --- /DELETAR ---
        elif texto_lower.startswith("/deletar"):
            try:
                partes = texto.split()
                id_para_deletar = int(partes[1])
                gasto = db.query(Gasto).filter(Gasto.id == id_para_deletar).first()
                if gasto:
                    db.delete(gasto)
                    db.commit()
                    resposta = f"✅ Gasto <b>ID {id_para_deletar}</b> (R$ {gasto.valor:.2f}) foi deletado."
                else:
                    resposta = f"❌ Gasto com <b>ID {id_para_deletar}</b> não encontrado."
            except (IndexError, ValueError):
                resposta = "❌ Use <code>/deletar [ID]</code> para apagar um gasto."

        # --- /ZERARTUDO ---
        elif texto_lower.startswith("/zerartudo"):
            partes = texto.split()
            if len(partes) == 2 and partes[1] == "confirmar":
                num = db.query(Gasto).delete()
                db.commit()
                resposta = f"🔥 Todos os <b>{num}</b> gastos foram apagados!"
            else:
                resposta = (
                    "⚠️ <b>Atenção!</b>\n"
                    "Isso apagará TODOS os gastos.\n"
                    "Se tem certeza, envie:\n"
                    "<code>/zerartudo confirmar</code>"
                )

        # --- SALVAR NOVO GASTO ---
        else:
            try:
                match = re.match(r'([\d\.,]+)\s*\"([^\"]+)\"\s*(.*)', texto, re.IGNORECASE)
                if match:
                    valor = float(match.group(1).replace(",", "."))
                    categoria = match.group(2).strip()
                    descricao = match.group(3).strip() or None
                else:
                    partes = texto.split()
                    valor = float(partes[0].replace(",", "."))
                    categoria = partes[1]
                    descricao = " ".join(partes[2:]) if len(partes) > 2 else None
                    aviso = (
                        f"⚠️ Categoria '{categoria}' foi salva como uma palavra.\n"
                        "Use aspas para categorias com mais de uma palavra."
                    )
                    await send_message(chat_id, aviso)

                novo = Gasto(valor=valor, categoria=categoria.lower(), descricao=descricao)
                db.add(novo)
                db.commit()
                db.refresh(novo)
                print(f"💾 Novo gasto salvo: ID={novo.id}, valor={valor}, categoria={categoria}")
                resposta = (
                    f"✅ Gasto salvo!\n"
                    f"<b>ID:</b> {novo.id}\n<b>Valor:</b> R$ {valor:.2f}\n"
                    f"<b>Categoria:</b> {categoria.lower()}"
                )
            except Exception as e:
                print(f"❌ Erro ao salvar gasto: {e}")
                resposta = (
                    "❌ Formato inválido. Use:\n"
                    "<code>VALOR CATEGORIA</code>\n"
                    "ou <code>VALOR \"CATEGORIA COM ASPAS\" descrição</code>"
                )

        await send_message(chat_id, resposta)

    except Exception as e:
        print(f"💥 ERRO FATAL NA FUNÇÃO WEBHOOK: {e}")
        await send_message(chat_id, "❌ Ocorreu um erro interno. Tente novamente mais tarde.")

    print("--------------------------------------------------")
    return {"status": "ok"}
