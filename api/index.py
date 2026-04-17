import os
import json
import re
import requests
import tempfile
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

conversations = {}
user_settings = {}

def fmt(val):
    try:
        if val is None: return 0
        f = float(val)
        return int(f) if f.is_integer() else f
    except:
        return val

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

def ask_ai(text: str, pending_context: dict = None, photo_url: str = None) -> str:
    system_prompt = """You are a Chartered Accountant (CA) and financial advisor for an ecommerce company called De Markt.

Your responsibilities:
- Understand natural language financial inputs (English, Bangla, mixed)
- Extract transactions correctly
- Classify into: income, expense, liability
- Categorize properly (sales, rent, salary, transport, vendor_due, etc.)
- Manage vendor dues, salaries, ads, and expenses
- Track cash, bank, and liabilities
- Ask follow-up questions when needed
- Behave like a human finance manager (not a robot)

IMPORTANT RULES:
1. If user message contains a transaction, return ONLY valid JSON in this format:
{
  "transactions": [
    {
      "amount": number,
      "type": "income|expense|liability",
      "category": "string",
      "note": "original text"
    }
  ]
}

2. If the message is NOT a transaction, reply like a human CA:
- answer questions
- ask relevant follow-up
- guide the user

3. If information is incomplete, ask short follow-up questions.
Examples:
- Which vendor?
- Cash or bank?
- Paid or due?
- Amount?

4. Always be short, clear, professional, and human.

5. Understand:
- sales = income
- rent / salary / ads = expense
- borrowed / supplier due = liability

6. Never return broken JSON.

8. If the user's setup or onboarding reply is ambiguous (e.g. combining bank and cash as one number), explicitly ask: "Please break it down: cash, bank, and bkash separately."
9. If multiple lines are sent, extract multiple transactions."""

    context_str = f"\n\nPending Context: {json.dumps(pending_context)}" if pending_context else ""
    user_content = []
    if text: user_content.append({"type": "text", "text": text})
    if photo_url: user_content.append({"type": "image_url", "image_url": {"url": photo_url}})
    
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
        return "{}"

@app.get("/cron")
async def run_cron():
    targets = list(user_settings.keys())
    if ADMIN_CHAT_ID and int(ADMIN_CHAT_ID) not in targets:
        targets.append(int(ADMIN_CHAT_ID))
    for cid in targets:
        send_message(cid, "De Markt day-end update\n\nReply shortly:\n- total sales?\n- any vendor purchase/payment?\n- total expenses?\n- any salary paid?\n- ad spend today?\n- founder withdrawal/investment?\n- any bills paid?")
    return {"ok": True}

@app.post("/webhook")
async def webhook(request: Request):
    try: update = await request.json()
    except: return {"ok": True}

    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = str(msg.get("text", msg.get("caption", ""))).strip()

    if not chat_id: return {"ok": True}

    try:
        print(f"DEBUG INCOMING: Chat: {chat_id} | Text: {text}")
        
        # Load Memory Profile implicitly
        pending = conversations.get(chat_id, {"history": [], "onboarding_mode": False})
        
        trigger_words = ["you are hired", "start", "setup", "manage my finance"]
        if any(tw in text.lower() for tw in trigger_words):
            if not pending.get("onboarding_mode"):
                pending["onboarding_mode"] = True
                print("DEBUG: Activating implicit onboarding mode")

        # Document check for Excel processing
        document = msg.get("document", {})
        if document.get("file_name", "").endswith(".xlsx"):
            import openpyxl
            f_res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={document['file_id']}").json()
            if f_res.get("ok"):
                send_message(chat_id, "Processing Excel file. Standby...")
                doc_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f_res['result']['file_path']}"
                r = requests.get(doc_url)
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                    tmp.write(r.content)
                    tmp_path = tmp.name
                try:
                    wb = openpyxl.load_workbook(tmp_path, data_only=True)
                    ws = wb.active
                    headers = [str(c.value).strip().lower() for c in ws[1] if c.value]
                    products_saved = 0
                    for row in ws.iter_rows(min_row=2, values_only=True):
                        if not row[0]: continue
                        p_data = dict(zip(headers, row))
                        name = str(p_data.get("product_name", row[0]))
                        if supabase:
                            supabase.table("transactions").insert({
                                "type": "product_master",
                                "category": name,
                                "amount": float(p_data.get("selling_price", 0) or 0),
                                "note": json.dumps({
                                    "sku": str(p_data.get("sku", "")),
                                    "cost_price": float(p_data.get("cost_price", 0) or 0),
                                    "selling_price": float(p_data.get("selling_price", 0) or 0),
                                    "stock_qty": int(p_data.get("stock_qty", 0) or 0),
                                    "status": str(p_data.get("status", "active"))
                                }),
                                "source": "telegram"
                            }).execute()
                            products_saved += 1
                    send_message(chat_id, f"Successfully imported {products_saved} products to memory.")
                except Exception as e:
                    send_message(chat_id, f"Excel Import Error: {str(e)}")
                os.remove(tmp_path)
                return {"ok": True}

        photo_url = None
        if "photo" in msg:
            file_id = msg["photo"][-1]["file_id"]
            f_res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}").json()
            if f_res.get("ok"):
                photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f_res['result']['file_path']}"

        if not text and not photo_url: return {"ok": True}
        if chat_id not in user_settings: user_settings[chat_id] = "22:00"

        # Command Execution
        if text.startswith("/"):
            commands = [c.strip().lower() for c in re.split(r'[,\n]+', text) if c.strip()]
            responses = []
            try:
                for cmd in commands:
                    if cmd == "/products":
                        if supabase:
                            res = supabase.table("transactions").select("category, amount, note").eq("type", "product_master").order("created_at", desc=False).execute()
                            active_items = {}
                            for r in res.data: active_items[r['category']] = r
                            s = "Product Database:\n"
                            for k, v in active_items.items(): s += f"- {k} (Selling: {fmt(v['amount'])})\n"
                            responses.append(s)
                    elif cmd.startswith("/product"):
                        parts = cmd.split(maxsplit=1)
                        if len(parts) > 1 and supabase:
                            res = supabase.table("transactions").select("*").eq("type", "product_master").eq("category", parts[1]).order("created_at", desc=True).limit(1).execute()
                            if res.data:
                                n = json.loads(res.data[0].get("note", "{}"))
                                responses.append(f"Product: {res.data[0]['category']}\nSelling Price: {fmt(res.data[0]['amount'])}\nCost Price: {fmt(n.get('cost_price',0))}\nStock: {n.get('stock_qty',0)}\nSKU: {n.get('sku','')}")
                            else: responses.append("Product not found.")
                    elif cmd == "/summary":
                        if supabase:
                            transactions = supabase.table("transactions").select("*").execute().data
                            income = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "income")
                            expense = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "expense")
                            liability = sum(float(t.get("amount") or 0) for t in transactions if t.get("type") == "liability")
                            responses.append(f"Summary\nIncome: {fmt(income)}\nExpense: {fmt(expense)}\nLiability: {fmt(liability)}\nBalance: {fmt(income-expense)}")
            except Exception as e:
                 responses.append(f"Command Error: {str(e)}")
            if responses: send_message(chat_id, "\n\n".join(responses))
            return {"ok": True}

        # Remove slash commands specifically from text before assessing general safety constraint
        base_text = text
        if base_text.startswith("/"):
            base_text = ""
            
        has_number = bool(re.search(r'\d', text))
        is_command = text.startswith("/")

        # Extract dynamic DB Context for conversational AI routing
        if supabase:
            try:
                txs = supabase.table("transactions").select("amount, type, category, note").order("created_at", desc=True).limit(30).execute().data
                pending["recent_database_memory"] = txs
            except Exception as e:
                print("DEBUG: DB Context fetch failed", e)

        # AI Processing
        print(f"DEBUG USER: {text}")
        ai_res = ask_ai(text, pending, photo_url)
        print(f"DEBUG AI RAW: {ai_res}")

        if not ai_res or str(ai_res).strip() in ["{}", "[]", "None", "null"]:
            final_reply = "Sorry, I didn’t understand. Can you rephrase?"
            print(f"DEBUG FINAL REPLY: {final_reply}")
            send_message(chat_id, final_reply)
            return {"ok": True}

        # Retain history window natively 
        pending["history"].append({"role": "user", "content": text})
        pending["history"].append({"role": "assistant", "content": ai_res})
        if len(pending["history"]) > 6: pending["history"] = pending["history"][-6:]
        conversations[chat_id] = pending

        try:
            parsed = json.loads(ai_res)
            print(f"DEBUG PARSED JSON: {parsed}")
        except Exception as json_err:
            print(f"DEBUG JSON FAILED: {json_err}")
            # If response is not JSON, it is a conversational CA-style reply natively
            final_reply = str(ai_res).strip()
            if not final_reply or final_reply in ["{}", "[]"]: final_reply = "Something went wrong. Please try again."
            print(f"DEBUG FINAL REPLY: {final_reply}")
            send_message(chat_id, final_reply)
            return {"ok": True}

        if "transactions" in parsed and isinstance(parsed["transactions"], list) and len(parsed["transactions"]) > 0:
            if not has_number and not is_command:
                # Safety Rule: if the message has NO number and is NOT a command, ignore JSON payload logic 
                print("DEBUG: Safety block activated. Passing JSON structurally as text due to zero digits.")
                # Extrapolate conversational content cleanly 
                final_reply = str(parsed.get("ca_reply", parsed.get("message", ai_res))).strip()
                if not final_reply or final_reply == "{}": final_reply = "Something went wrong. Please try again."
                print(f"DEBUG FINAL REPLY: {final_reply}")
                send_message(chat_id, final_reply)
                return {"ok": True}
            
            reply_lines = ["Saved:"]
            for t in parsed["transactions"]:
                amount = t.get("amount", 0)
                t_type = t.get("type", "expense")
                category = t.get("category", "general")
                note = t.get("note", text)
                
                if supabase:
                    supabase.table("transactions").insert({
                        "amount": amount,
                        "type": t_type,
                        "category": category,
                        "note": note,
                        "source": "telegram"
                    }).execute()
                
                reply_lines.append(f"- {category}: {amount} ({t_type})")
                
            final_reply = "\n".join(reply_lines)
            if not final_reply.strip(): final_reply = "Something went wrong. Please try again."
            print(f"DEBUG FINAL REPLY: {final_reply}")
            send_message(chat_id, final_reply)
            return {"ok": True}

        # If the JSON doesn't contain a transactions list (maybe valid JSON hallucination format), pass it natively.
        final_reply = str(parsed.get("ca_reply", parsed.get("message", parsed.get("transactions", ai_res)))).strip()
        if not final_reply or final_reply in ["None", "{}", "[]"]: final_reply = "Something went wrong. Please try again."
        print(f"DEBUG FINAL REPLY: {final_reply}")
        send_message(chat_id, final_reply)
        return {"ok": True}

    except Exception as master_err:
        print(f"DEBUG CRITICAL APP FAILURE: {str(master_err)}")
        send_message(chat_id, "System error. Please send again.")
        return {"ok": True}