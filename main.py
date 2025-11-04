from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from typing import Optional

# Importações dos nossos novos arquivos
from database import Base, engine, get_db
from models import Update # Apenas o Pydantic Update é necessário aqui
from telegram import send_message
from bot_logic import processar_mensagem

# 1. Cria a "aplicação" FastAPI
app = FastAPI()

# --- FUNÇÃO DE INICIALIZAÇÃO ---
@app.on_event("startup")
def on_startup():
    print("Iniciando: Verificando/Criando tabelas do banco de dados...")
    try:
        Base.metadata.create_all(bind=engine)
        print("Sucesso: Tabelas verificadas/criadas.")
    except Exception as e:
        print(f"ERRO CRÍTICO DURANTE CRIAÇÃO DAS TABELAS: {e}")

# --- WEBHOOK PRINCIPAL (AGORA MUITO MAIS LIMPO) ---
@app.post("/webhook")
async def webhook(update: Update, db: Session = Depends(get_db)):
    
    # Verifica se a mensagem tem os dados que precisamos
    if not update.message or not update.message.from_user or not update.message.text:
        print("Mensagem recebida sem texto ou dados do usuário, ignorando.")
        return {"status": "ok"}
    
    chat_id = update.message.chat.id
    texto = update.message.text
    nome_usuario = update.message.from_user.first_name
    user_id = update.message.from_user.id

    print(f"--- MENSAGEM RECEBIDA (Chat ID: {chat_id}, User ID: {user_id}) ---")
    print(f"De: {nome_usuario} | Texto: {texto}")

    resposta = ""
    parse_mode = "HTML"
    aviso_aspas = ""
    mensagem_foi_enviada = False

    # Bloco try/except principal
    try:
        # 1. Delega TODO o trabalho para o bot_logic
        (resposta, parse_mode, aviso_aspas) = processar_mensagem(db, user_id, texto, nome_usuario)

        # 2. Envia a resposta principal (se houver)
        if resposta:
            print(f"-> Preparando para enviar resposta (ParseMode={parse_mode}): '{resposta[:50]}...'")
            await send_message(chat_id, resposta, parse_mode=parse_mode)
            mensagem_foi_enviada = True
        
        # 3. Envia o aviso de aspas (se houver)
        if aviso_aspas and mensagem_foi_enviada and resposta.startswith("✅"):
             print("-> Enviando aviso sobre aspas...")
             await send_message(chat_id, aviso_aspas)

    except Exception as e:
        print(f"💥 ERRO FATAL NA FUNÇÃO WEBHOOK: {e}")
        try:
            if not mensagem_foi_enviada:
                 await send_message(chat_id, "❌ Desculpe, ocorreu um erro fatal no servidor. Tente novamente.")
        except:
            pass # Ignora se até o envio de erro falhar

    print("--------------------------------------------------")
    return {"status": "ok"} # Sempre retorna OK para o Telegram
