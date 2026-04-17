import os
import json
import re
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

def fmt(val):
    try:
        f = float(val)
        return int(f) if f.is_integer() else f
    except:
        return val

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    resp = requests.post(url, json=payload)
    print("Telegram status:", resp.status_code)
    print("Telegram response:", resp.text)

def ask_ai(text: str) -> str:
    system_prompt = """You are an accounting data extractor.
Return ONLY valid JSON.
No markdown.
No explanation.
No extra text.

Schema:
{
  "amount": number,
  "type": "income" | "expense" | "liability",
  "category": string
}

Rules:
- "sales", "sale", "revenue", "income" => type = "income", category = "sales"
- "rent" => type = "expense", category = "rent"
- "salary", "wage", "payroll" => type = "expense", category = "salary"
- "transport", "fuel", "fare" => type = "expense", category = "transport"
- "bought laptop", "laptop", "computer", "printer", "equipment" => type = "expense", category = "equipment"
- "borrowed", "loan" => type = "liability", category = "loan"
- "supplier due", "unpaid supplier", "supplier payable" => type = "liability", category = "supplier_due"
- Extract numeric amount from the message

Examples:

Input: sales 5000
Output: {"amount":5000,"type":"income","category":"sales"}

Input: rent 1200
Output: {"amount":1200,"type":"expense","category":"rent"}

Input: salary 5000
Output: {"amount":5000,"type":"expense","category":"salary"}

Input: bought laptop 20000
Output: {"amount":20000,"type":"expense","category":"equipment"}

Input: transport 300
Output: {"amount":300,"type":"expense","category":"transport"}

Input: borrowed 10000
Output: {"amount":10000,"type":"liability","category":"loan"}

Input: supplier due 5000
Output: {"amount":5000,"type":"liability","category":"supplier_due"}"""

    try:
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "mistralai/mistral-7b-instruct",
                "messages": [
                    {"role": "system", "content": system_prompt},
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

    if text.strip().lower() == "/summary":
        if not supabase:
            send_message(chat_id, "Database not configured.")
            return {"ok": True}
        
        try:
            res = supabase.table("transactions").select("*").execute()
            transactions = res.data
            
            income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
            expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
            liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
            balance = income - expense
            
            reply = f"Summary\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nBalance: {fmt(balance)}"
        except Exception as e:
            print("SUMMARY ERROR:", str(e))
            reply = "Could not generate summary."
            
        send_message(chat_id, reply)
        return {"ok": True}

    if text.strip().lower() == "/today":
        if not supabase:
            send_message(chat_id, "Database not configured.")
            return {"ok": True}
        
        try:
            from datetime import datetime, timezone
            today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            res = supabase.table("transactions").select("*").gte("created_at", today_date).execute()
            transactions = res.data
            
            income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
            expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
            liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
            balance = income - expense
            
            reply = f"Today\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nBalance: {fmt(balance)}"
        except Exception as e:
            print("TODAY ERROR:", str(e))
            reply = "Could not generate today's summary."
            
        send_message(chat_id, reply)
        return {"ok": True}

    if text.strip().lower() == "/monthly":
        if not supabase:
            send_message(chat_id, "Database not configured.")
            return {"ok": True}
        
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            month_start = f"{now.year}-{now.month:02d}-01"
            res = supabase.table("transactions").select("*").gte("created_at", month_start).execute()
            transactions = res.data
            
            income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
            expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
            liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
            profit_loss = income - expense
            
            reply = f"Monthly Report\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nProfit/Loss: {fmt(profit_loss)}"
        except Exception as e:
            print("MONTHLY ERROR:", str(e))
            reply = "Could not generate monthly report."
            
        send_message(chat_id, reply)
        return {"ok": True}

    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if not lines:
        return {"ok": True}

    saved_count = 0
    results = []

    for line in lines:
        ai_response = ask_ai(line)
        print(f"RAW AI ({line}):", ai_response)

        try:
            parsed = json.loads(ai_response.strip())
            print(f"PARSED ({line}):", parsed)
        except Exception as e:
            print(f"Parsing error for line '{line}':", e)
            if len(lines) == 1:
                send_message(chat_id, f"AI raw: {ai_response}")
                return {"ok": True}
            continue

        try:
            amount = parsed.get("amount", 0)
            type_ = parsed.get("type", "")
            category = parsed.get("category", "")

            # Fallback logic for amount
            numbers_in_text = re.findall(r'\d+(?:\.\d+)?', line)
            if (not amount or amount == 0) and numbers_in_text:
                amount = float(numbers_in_text[0])

            # Fallback logic for classification
            if not type_ or not category:
                text_lower = line.lower()
                if "rent" in text_lower:
                    type_ = "expense"
                    category = "rent"
                elif "salary" in text_lower:
                    type_ = "expense"
                    category = "salary"
                elif "transport" in text_lower:
                    type_ = "expense"
                    category = "transport"
                elif "laptop" in text_lower:
                    type_ = "expense"
                    category = "equipment"
                elif "borrowed" in text_lower:
                    type_ = "liability"
                    category = "loan"
                elif "supplier due" in text_lower:
                    type_ = "liability"
                    category = "supplier_due"
                elif "sales" in text_lower:
                    type_ = "income"
                    category = "sales"

            if supabase:
                supabase.table("transactions").insert({
                    "amount": amount,
                    "type": type_,
                    "category": category,
                    "note": line,
                    "source": "telegram"
                }).execute()

            saved_count += 1
            if len(lines) == 1:
                send_message(chat_id, f"Saved\nAmount: {fmt(amount)}\nType: {type_}\nCategory: {category}\nNote: {line}")
                return {"ok": True}
            else:
                results.append(f"{saved_count}.\nAmount: {fmt(amount)}\nType: {type_}\nCategory: {category}")

        except Exception as e:
            print(f"ERROR processing line '{line}':", str(e))
            if len(lines) == 1:
                send_message(chat_id, "Database saving error.")
                return {"ok": True}
            continue

    if len(lines) > 1:
        if saved_count > 0:
            reply = f"Saved {saved_count} transactions:\n\n" + "\n\n".join(results)
            send_message(chat_id, reply)
        else:
            send_message(chat_id, "Error: No transactions could be saved.")

    return {"ok": True}