import os
import json
import requests
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

# Note: os.getenv takes the env var name as the first argument. I am providing your tokens as the fallback.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8770543275:AAE4OOVZAf-WxAKPLeikDmdv7Jd-Bi8lWg0")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://wonzungmwsqhpivagxeq.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_DHHG0fzJbtAisJS4IuFtMQ_OwTKfmap")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "29ef8baee3f04b6f9c602bcf98c155acd1c4d93401d5b14777fd4b2da0f2a173")

app = FastAPI()

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    resp = requests.post(url, json=payload)
    print("Telegram status:", resp.status_code)
    print("Telegram response:", resp.text)

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