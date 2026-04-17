import os
import json
import requests
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

# Initialize supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

app = FastAPI()

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    resp = requests.post(url, json=payload)
    print("Telegram status:", resp.status_code)
    print("Telegram response:", resp.text)

def ask_ai(text: str) -> str:
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
        
        raw_content = res.json()["choices"][0]["message"]["content"].strip()
        
        # Cleanup any potential markdown formatted JSON output
        if raw_content.startswith("```json"):
            raw_content = raw_content[7:]
        if raw_content.endswith("```"):
            raw_content = raw_content[:-3]
            
        return raw_content.strip()
    except Exception as e:
        print("ask_ai ERROR:", str(e))
        return "{}"

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

    ai_response = ask_ai(text)
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

    send_message(chat_id, reply)

    return {"ok": True}