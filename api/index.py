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
    system_prompt = """You are an AI accountant for "De Markt", an ecommerce gadget brand in BDT.
Return ONLY valid JSON. No markdown. No explanations.

Schema:
{
  "amount": number,
  "type": "income" | "expense" | "liability" | "owner",
  "category": string,
  "vendor_name": string (optional),
  "due": number (optional),
  "employee_role": string (optional),
  "ad_platform": string (optional)
}

Allowed Categories:
- Income: sales_courier, sales_direct, sales_online
- Expenses: transport, salary_ops, salary_smm, salary_graphic_designer, salary_marketing, office_rent, internet_bill, utility_bill, ad_spend_facebook, ad_spend_tiktok, ad_spend_google, office_expense
- Liabilities: vendor_due, unpaid_salary, unpaid_bill, loan
- Owner: founder_withdrawal, founder_investment

Rules:
1. Vendor due: If user mentions vendor purchase with partial payment, calculate due automatically. (e.g. "took product 300000 from Akhi Telecom paid 50000" => amount=250000, due=250000, type="liability", category="vendor_due", vendor_name="Akhi Telecom")
2. Ad loading: If user mentions USD ad loading, convert to BDT automatically if rate is given. (e.g. "loaded 100 dollar for facebook ads at 133" => amount=13300, type="expense", category="ad_spend_facebook", ad_platform="facebook")
3. Founder withdrawal: Do not classify as expense. Use type="owner", category="founder_withdrawal".
4. Sales channels mapping: "courier" => sales_courier, "direct" => sales_direct, "online payment" => sales_online.
5. If important extra fields are found, provide vendor_name, employee_role, or ad_platform in the JSON.
"""

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

    text_stripped = text.strip()

    if text_stripped.startswith("/"):
        if not supabase:
            send_message(chat_id, "Database not configured.")
            return {"ok": True}

        # Handle both comma and newline delimited commands
        commands = [c.strip().lower() for c in re.split(r'[,\n]+', text_stripped) if c.strip()]
        responses = []

        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            
            for cmd in commands:
                if cmd == "/summary":
                    res = supabase.table("transactions").select("*").execute()
                    transactions = res.data
                    income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
                    expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
                    liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
                    balance = income - expense
                    responses.append(f"Summary\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nBalance: {fmt(balance)}")
                
                elif cmd == "/today":
                    today_date = now.strftime("%Y-%m-%d")
                    res = supabase.table("transactions").select("*").gte("created_at", today_date).execute()
                    transactions = res.data
                    income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
                    expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
                    liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
                    balance = income - expense
                    responses.append(f"Today\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nBalance: {fmt(balance)}")
                
                elif cmd == "/monthly":
                    month_start = f"{now.year}-{now.month:02d}-01"
                    res = supabase.table("transactions").select("*").gte("created_at", month_start).execute()
                    transactions = res.data
                    income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
                    expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
                    liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
                    profit_loss = income - expense
                    responses.append(f"Monthly Report\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nProfit/Loss: {fmt(profit_loss)}")
                
        except Exception as e:
            print("COMMAND ERROR:", str(e))
            responses.append("Could not generate report.")
            
        send_message(chat_id, "\n\n".join(responses) if responses else "Unknown command.")
        return {"ok": True}

    # Transaction parsing lines
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if not lines:
        return {"ok": True}

    saved_count = 0
    results = []

    for line in lines:
        if line.startswith("/"):
            continue # Extra safeguard just in case mixed block is passed

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
            vendor_name = parsed.get("vendor_name")
            due = parsed.get("due")
            employee_role = parsed.get("employee_role")
            ad_platform = parsed.get("ad_platform")

            # Generic fallback if AI totally fails amount extraction
            numbers_in_text = re.findall(r'\d+(?:\.\d+)?', line)
            if (not amount or amount == 0) and numbers_in_text:
                amount = float(numbers_in_text[0])

            # Build metadata payload into the note string
            final_note = line
            extras = []
            if vendor_name: extras.append(f"Vendor: {vendor_name}")
            if due is not None: extras.append(f"Due: {fmt(due)}")
            if employee_role: extras.append(f"Role: {employee_role}")
            if ad_platform: extras.append(f"Platform: {ad_platform}")
            
            if extras:
                final_note += " | " + ", ".join(extras)

            if supabase:
                supabase.table("transactions").insert({
                    "amount": amount,
                    "type": type_,
                    "category": category,
                    "note": final_note,
                    "source": "telegram"
                }).execute()

            saved_count += 1
            
            reply_lines = [
                "Saved" if len(lines) == 1 else f"{saved_count}.",
                f"Amount: {fmt(amount)}",
                f"Type: {type_}",
                f"Category: {category}"
            ]
            if len(lines) == 1:
                reply_lines.append(f"Note: {line}")

            if vendor_name: reply_lines.append(f"Vendor: {vendor_name}")
            if due is not None: reply_lines.append(f"Due: {fmt(due)}")
            if employee_role: reply_lines.append(f"Role: {employee_role}")
            if ad_platform: reply_lines.append(f"Platform: {ad_platform}")

            reply_str = "\n".join(reply_lines)

            if len(lines) == 1:
                send_message(chat_id, reply_str)
                return {"ok": True}
            else:
                results.append(reply_str)

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