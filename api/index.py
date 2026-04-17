import os
import json
import requests
from fastapi import FastAPI, Request
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

def send_message(chat_id: int, text: str):
    if not BOT_TOKEN: return
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )
    print("Telegram send status:", resp.status_code)
    print("Telegram send body:", resp.text)

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return {"status": "error", "message": "invalid json"}

    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text")

    print("Incoming chat_id:", chat_id)
    print("Incoming text:", text)

    if not chat_id or not text:
        return {"ok": True}

    send_message(chat_id, f"Echo: {text}")

    return {"ok": True}