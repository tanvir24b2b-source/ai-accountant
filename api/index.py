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
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
app = FastAPI()

# Ephemeral State Management
conversations = {}
user_settings = {}

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
    print("Telegram send:", resp.status_code)

def ask_ai(text: str, pending_context: dict = None, photo_url: str = None) -> str:
    system_prompt = """You are an AI chartered accountant for "De Markt", an ecommerce gadget brand in BDT.
    
Schema:
{
  "amount": number or null,
  "type": "income" | "expense" | "liability" | "owner" or null,
  "category": string or null,
  "vendor_name": string or null,
  "due": number or null,
  "employee_role": string or null,
  "ad_platform": string or null,
  "ca_note": string (optional, 1-2 sentence professional chartered accountant observation. Short, proactive guidance.),
  "is_complete": boolean (true ONLY if amount, type, and category are ALL firmly defined and valid string types. If any of the three are ambiguous or missing, false)
}

Allowed Categories:
- Income: sales_courier, sales_direct, sales_online
- Expenses: transport, salary_ops, salary_smm, salary_graphic_designer, salary_marketing, office_rent, internet_bill, utility_bill, ad_spend_facebook, ad_spend_tiktok, ad_spend_google, office_expense
- Liabilities: vendor_due, unpaid_salary, unpaid_bill, loan
- Owner: founder_withdrawal, founder_investment

Rules:
1. You may receive partial statements or invoice photos. Merge them with the Pending Context organically. 
2. If `amount`, `type`, and `category` are decisively established correctly, set `is_complete: true`. Otherwise `is_complete: false`.
3. If partial payment, calculate due.
4. Ad loading: $ -> BDT if rate given.
5. Provide a very brief CA note (e.g. "Vendor payable increased today. We should plan a payment.") if relevant.
6. Do NOT add extra text. ONLY return valid JSON."""

    context_str = f"\n\nPending Context: {json.dumps(pending_context)}" if pending_context else ""
    
    user_content = []
    if text:
        user_content.append({"type": "text", "text": text})
    if photo_url:
        user_content.append({"type": "image_url", "image_url": {"url": photo_url}})
    
    if not user_content: return "{}"

    try:
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt + context_str},
                    {"role": "user", "content": user_content}
                ]
            }
        )
        res.raise_for_status()
        raw_content = res.json()["choices"][0]["message"]["content"].strip()
        if raw_content.startswith("```json"): raw_content = raw_content[7:]
        if raw_content.endswith("```"): raw_content = raw_content[:-3]
        return raw_content.strip()
    except Exception as e:
        print("ask_ai ERROR:", str(e))
        return "{}"

@app.get("/cron")
async def run_cron():
    """Triggered by Vercel crons globally."""
    targets = list(user_settings.keys())
    if ADMIN_CHAT_ID and int(ADMIN_CHAT_ID) not in targets:
        targets.append(int(ADMIN_CHAT_ID))
        
    for cid in targets:
        send_message(cid, "De Markt day-end update\n\nReply shortly:\n- total sales?\n- any vendor purchase/payment?\n- total expenses?\n- any salary paid?\n- ad spend today?\n- founder withdrawal/investment?\n- any bills paid?")
        
    return {"ok": True, "pinged": len(targets)}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return {"status": "error"}

    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", msg.get("caption", "")).strip()

    photo_url = None
    if "photo" in msg:
        file_id = msg["photo"][-1]["file_id"]
        f_res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}").json()
        if f_res.get("ok"):
            file_path = f_res["result"]["file_path"]
            photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    if not chat_id or (not text and not photo_url):
        return {"ok": True}

    if chat_id not in user_settings:
        user_settings[chat_id] = "22:00"

    # Command Execution
    if text.startswith("/"):
        commands = [c.strip().lower() for c in re.split(r'[,\n]+', text) if c.strip()]
        responses = []

        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            
            for cmd in commands:
                if cmd.startswith("/setcheckin"):
                    parts = cmd.split()
                    if len(parts) > 1:
                        user_settings[chat_id] = parts[1]
                        responses.append(f"Check-in updated to {parts[1]} (Note: Vercel limits dynamic background timers structurally. Fixed timing executes nightly).")
                    else:
                        responses.append("Format: /setcheckin HH:MM")
                        
                elif cmd == "/summary":
                    if supabase:
                        res = supabase.table("transactions").select("*").execute()
                        transactions = res.data
                        income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
                        expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
                        liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
                        balance = income - expense
                        responses.append(f"Summary\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nBalance: {fmt(balance)}")
                
                elif cmd == "/today":
                    if supabase:
                        today_date = now.strftime("%Y-%m-%d")
                        res = supabase.table("transactions").select("*").gte("created_at", today_date).execute()
                        transactions = res.data
                        income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
                        expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
                        liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
                        balance = income - expense
                        responses.append(f"Today\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nBalance: {fmt(balance)}")
                
                elif cmd == "/monthly":
                    if supabase:
                        month_start = f"{now.year}-{now.month:02d}-01"
                        res = supabase.table("transactions").select("*").gte("created_at", month_start).execute()
                        transactions = res.data
                        income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
                        expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
                        liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
                        profit_loss = income - expense
                        responses.append(f"Monthly Report\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nProfit/Loss: {fmt(profit_loss)}")
                
        except Exception as e:
             responses.append("Could not process command.")
             
        if responses: send_message(chat_id, "\n\n".join(responses))
        return {"ok": True}

    # Batch Check
    lines = [line.strip() for line in text.split('\n') if line.strip() and not line.startswith("/")]
    if not lines and photo_url:
        lines = ["Process this invoice matching De Markt logic."]
    elif not lines:
        return {"ok": True}

    if len(lines) > 1 and not photo_url:
        saved_count = 0
        results = []
        for line in lines:
            ai_res = ask_ai(line)
            try:
                parsed = json.loads(ai_res)
                amount = parsed.get("amount") or 0
                number_match = re.findall(r'\d+(?:\.\d+)?', line)
                if not amount and number_match: amount = float(number_match[0])
                if not amount or not parsed.get("type") or not parsed.get("category"): continue
                
                final_note = line
                extras = []
                if parsed.get("vendor_name"): extras.append(f"Vendor: {parsed.get('vendor_name')}")
                if parsed.get("due") is not None: extras.append(f"Due: {fmt(parsed.get('due'))}")
                if parsed.get("employee_role"): extras.append(f"Role: {parsed.get('employee_role')}")
                if parsed.get("ad_platform"): extras.append(f"Platform: {parsed.get('ad_platform')}")
                if extras: final_note += " | " + ", ".join(extras)
                
                if supabase: supabase.table("transactions").insert({"amount": amount, "type": parsed.get("type"), "category": parsed.get("category"), "note": final_note, "source": "telegram"}).execute()
                saved_count += 1
                results.append(f"{saved_count}.\nAmount: {fmt(amount)}\nType: {parsed.get('type')}\nCategory: {parsed.get('category')}")
            except: continue
        if saved_count > 0:
            send_message(chat_id, f"Saved {saved_count} transactions:\n\n" + "\n\n".join(results))
        return {"ok": True}

    # Conversational Phase (Single Line or Photo)
    line = lines[0]
    pending = conversations.get(chat_id, {})
    ai_res = ask_ai(line, pending, photo_url)
    
    try:
        parsed = json.loads(ai_res)
    except:
        send_message(chat_id, "Sorry, I couldn't process that entry properly.")
        return {"ok": True}

    conversations[chat_id] = parsed

    if not parsed.get("is_complete"):
        if not parsed.get("amount"):
            send_message(chat_id, "Amount?")
        elif not parsed.get("type"):
            send_message(chat_id, "Expense, income, or liability?")
        elif not parsed.get("category"):
            send_message(chat_id, "Which exact category from the sheet?")
        else:
            send_message(chat_id, "Missing core details. Please clarify.")
        return {"ok": True}

    amount = parsed.get("amount", 0)
    number_match = re.findall(r'\d+(?:\.\d+)?', line)
    if not amount and number_match: amount = float(number_match[0])

    final_note = line
    extras = []
    if parsed.get("vendor_name"): extras.append(f"Vendor: {parsed.get('vendor_name')}")
    if parsed.get("due") is not None: extras.append(f"Due: {fmt(parsed.get('due'))}")
    if parsed.get("employee_role"): extras.append(f"Role: {parsed.get('employee_role')}")
    if parsed.get("ad_platform"): extras.append(f"Platform: {parsed.get('ad_platform')}")
    if extras: final_note += " | " + ", ".join(extras)

    if supabase: 
        supabase.table("transactions").insert({
            "amount": amount, 
            "type": parsed.get("type"), 
            "category": parsed.get("category"), 
            "note": final_note, 
            "source": "telegram"
        }).execute()

    del conversations[chat_id]

    reply_str = f"Saved\nAmount: {fmt(amount)}\nType: {parsed.get('type')}\nCategory: {parsed.get('category')}\nNote: {line}"
    if extras: reply_str += "\n" + "\n".join(extras)
    
    if parsed.get("ca_note"):
        reply_str += f"\n\nCA Note:\n{parsed.get('ca_note')}"

    send_message(chat_id, reply_str)
    return {"ok": True}