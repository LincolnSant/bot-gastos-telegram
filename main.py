import httpx
from fastapi import FastAPI, Depends
from pydantic import BaseModel, Field
from typing import Optional, List # << Incluí o List que faltava
import os
from sqlalchemy.orm import Session
import re
from datetime import datetime, timedelta # <<< ADICIONADO PARA A LIMPEZA

# --- Imports do Banco de Dados ---
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, desc
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func
# ---------------------------------


# --- CONFIGURAÇÃO ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
# 🔧 CORREÇÃO AUTOMÁTICA PARA O RENDER (postgres:// → postgresql://)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1) # Corrigido para substituir apenas uma vez
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- Config do Banco de Dados ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- FUNÇÃO DE INJEÇÃO DE DEPENDÊNCIA ---
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

# --- FUNÇÃO DE INICIALIZAÇÃO ---
@app.on_event("startup")
def on_startup():
    print("Iniciando: Verificando/Criando tabelas do banco de dados...")
    try:
        Base.metadata.create_all(bind=engine)
        print("Sucesso: Tabelas verificadas/criadas.")
    except Exception as e:
        print(f"ERRO CRÍTICO DURANTE CRIAÇÃO DAS TABELAS: {e}")

# --- FUNÇÃO DE RESPOSTA (COM PARSE_MODE OPCIONAL E ERRO DETALHADO) --- # <<< CORRIGIDO AQUI
async def send_message(chat_id: int, text: str, parse_mode: Optional[str] = "HTML"):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode: # Adiciona parse_mode apenas se não for None
        payload["parse_mode"] = parse_mode

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                 print(f"⚠️ Telegram API Error {response.status_code}: {response.text}")
            response.raise_for_status() # Lança erro se for 4xx/5xx
        except httpx.HTTPStatusError as e:
            print(f"⚠️ Erro HTTP ao enviar mensagem: Status {e.response.status_code}")
            # Se o erro for por mensagem muito longa, loga isso especificamente
            if e.response.status_code == 400 and "message is too long" in e.response.text.lower():
                print(">>> ERRO DETECTADO: Mensagem excedeu o limite de 4096 caracteres do Telegram.")
        except Exception as e:
            print(f"⚠️ Erro inesperado ao enviar mensagem: {e}")


# --- (NOVO) FUNÇÃO DE LIMPEZA DE DADOS ---
def limpar_gastos_antigos(db: Session):
    # Define o período de 6 meses (aprox. 180 dias)
    dias_para_manter = 180
    data_limite = datetime.now() - timedelta(days=dias_para_manter)

    # Executa o DELETE no banco de dados
    num_deletados = db.query(Gasto).filter(
        Gasto.data_criacao < data_limite
    ).delete(synchronize_session=False)

    db.commit()

    print(f"🗑️ Limpeza executada. {num_deletados} gastos anteriores a {data_limite.strftime('%Y-%m-%d')} foram apagados.")
    return num_deletados
# ------------------------------------------


# --- WEBHOOK PRINCIPAL ---
@app.post("/webhook")
async def webhook(update: Update, db: Session = Depends(get_db)):
    chat_id = update.message.chat.id
    texto = update.message.text
    nome_usuario = update.message.from_user.first_name

    print(f"--- MENSAGEM RECEBIDA (Chat ID: {chat_id}) ---")
    print(f"De: {nome_usuario} | Texto: {texto}")

    resposta = ""
    parse_mode_para_resposta_atual = "HTML" # Padrão HTML
    mensagem_foi_enviada = False

    try:
        if texto:
            texto_lower = texto.lower().strip()

            # --- LÓGICA DO /START ---
            if texto_lower == "/start":
                resposta = f"Olá, <b>{nome_usuario}</b>! 👋\n\n"
                resposta += "Para anotar um gasto, envie:\n"
                resposta += "<code>VALOR \"CATEGORIA\" (descrição)</code>\n"
                resposta += "<b>Exemplo:</b> <code>15.50 padaria</code>\n"
                resposta += "<b>Exemplo:</b> <code>100 \"lava louça\"</code>\n\n"
                resposta += "Comandos:\n"
                resposta += "<code>/relatorio</code> | <code>/listar</code> | <code>/deletar [ID]</code> | <code>/zerartudo confirmar</code>\n\n"
                resposta += "ℹ️ <i>Gastos com mais de 6 meses são removidos automaticamente.</i>" # Removido <small>

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

            # --- LÓGICA DO /LISTAR (SEM HTML) --- # <<< CORRIGIDO AQUI
            elif texto_lower == "/listar":
                parse_mode_para_resposta_atual = None # Desliga HTML para esta resposta
                consulta = db.query(Gasto).order_by(Gasto.id.desc()).limit(5).all()
                resposta = "📋 Últimos 5 Gastos Registrados 📋\n\n"
                if not consulta:
                    resposta += "Nenhum gasto registrado ainda."
                else:
                    for gasto in consulta:
                        try:
                            data_formatada = "Sem Data"
                            if gasto.data_criacao:
                                data_formatada = gasto.data_criacao.strftime('%d/%m %H:%M')

                            linha = f"ID {gasto.id}: R$ {gasto.valor:.2f} ({gasto.categoria})"
                            if gasto.descricao:
                                linha += f" - {gasto.descricao}"
                            linha += f" [{data_formatada}]\n"
                            resposta += linha
                        except Exception as e:
                            print(f"⚠️ Erro ao formatar Gasto ID {gasto.id}: {e}")
                            resposta += f"⚠️ Erro ao exibir Gasto ID {gasto.id}\n"
                resposta += "\n(Mostrando os últimos 5)"

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
                        resposta = f"❌ Gasto com <b>ID {id_para_deletar}</b> não encontrado."

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
                            if len(partes) > 1 : # Avisa se tiver só valor e categoria
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
                         # Envia o aviso separadamente (mantendo HTML padrão)
                         await send_message(chat_id, aviso)


                except (ValueError, IndexError):
                    resposta = "❌ Formato inválido. Use <code>VALOR CATEGORIA</code> ou <code>/start</code>."

            # Envia a resposta SOMENTE se uma foi gerada
            if resposta:
                print(f"-> Preparando para enviar resposta (ParseMode={parse_mode_para_resposta_atual}): '{resposta[:50]}...'")
                # Passa o parse_mode correto para a função
                await send_message(chat_id, resposta, parse_mode=parse_mode_para_resposta_atual)
                mensagem_foi_enviada = True

    except Exception as e:
        print(f"💥 ERRO FATAL NA FUNÇÃO WEBHOOK: {e}")
        try:
            # Tenta enviar erro com HTML padrão
            await send_message(chat_id, "❌ Desculpe, ocorreu um erro fatal no servidor. Tente novamente.")
        except:
            pass

    print("--------------------------------------------------")
    return {"status": "ok"}
