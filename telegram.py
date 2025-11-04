import httpx
import os
from typing import Optional

# Pega o Token e a URL base das variáveis de ambiente
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- FUNÇÃO DE RESPOSTA (COM PARSE_MODE OPCIONAL) ---
async def send_message(chat_id: int, text: str, parse_mode: Optional[str] = "HTML"):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                 print(f"⚠️ Telegram API Error {response.status_code}: {response.text}")
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            print(f"⚠️ Erro HTTP ao enviar mensagem: Status {e.response.status_code}")
            if e.response.status_code == 400 and "message is too long" in e.response.text.lower():
                print(">>> ERRO DETECTADO: Mensagem excedeu o limite de 4096 caracteres do Telegram.")
        except Exception as e:
            print(f"⚠️ Erro inesperado ao enviar mensagem: {e}")
