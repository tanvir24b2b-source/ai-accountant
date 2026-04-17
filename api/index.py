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

def send_reply(chat_id: int, text: str):
    if not BOT_TOKEN: return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return {"status": "error", "message": "invalid json"}

    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text")

    if not chat_id or not text:
        return {"status": "ok"}

    print("Incoming:", text)

    try:
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "mistralai/mistral-7b-instruct",
                "messages": [
                    {"role": "system", "content": "You are an AI accountant. Extract amount, type (income/expense/liability), category. Return ONLY valid JSON."},
                    {"role": "user", "content": text}
                ]
            }
        )
        res.raise_for_status()
        ai_response = res.json()["choices"][0]["message"]["content"]
    except Exception:
        send_reply(chat_id, "API Error")
        return {"status": "error"}

    print("AI response:", ai_response)

    try:
        parsed = json.loads(ai_response)
        amount = parsed.get("amount", 0)
        type_ = parsed.get("type", "")
        category = parsed.get("category", "")

        supabase.table("transactions").insert({
            "amount": amount,
            "type": type_,
            "category": category,
            "note": text,
            "source": "telegram"
        }).execute()

        reply = f"Saved\nAmount: {amount}\nType: {type_}\nCategory: {category}"

    except Exception as e:
        print("ERROR:", str(e))
        reply = f"AI raw: {ai_response}"

    send_reply(chat_id, reply)

    return {"status": "ok"}