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
    system_prompt = """You are an AI chartered accountant for "De Markt", an ecommerce gadget brand in BDT.
    
Schema:
{
  "amount": number or null,
  "type": "income" | "expense" | "liability" | "owner" | null,
  "category": string or null,
  "vendor_name": string or null,
  "due": number or null,
  "employee_role": string or null,
  "ad_platform": string or null,
  "action": "product_update" | null,
  "product_name": string or null,
  "selling_price": number or null,
  "cost_price": number or null,
  "stock_qty": number or null,
  "ca_note": string (optional, 1-2 sentence professional guidance),
  "is_complete": boolean (true ONLY if amount, type, and category are firmly defined. false otherwise.)
}

Rules:
1. Merge interactions with Pending Context.
2. If `action` is "product_update", determine the target `product_name` and the `selling_price`, `cost_price`, or `stock_qty` from the message natively (e.g. "Airbuds price update 1450" => product_name: "Airbuds", selling_price: 1450).
3. If partial payment, calculate `due` automatically.
4. Ad loading: $ -> BDT if rate given.
5. Provide a CA note if financially relevant.
6. Do NOT add extra text. Return JSON only."""

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
    text = msg.get("text", msg.get("caption", "")).strip()

    if not chat_id: return {"ok": True}

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

    lines = [line.strip() for line in text.split('\n') if line.strip() and not line.startswith("/")]
    if not lines and photo_url: lines = ["Process this invoice"]
    elif not lines: return {"ok": True}

    # Converational Mode
    line = lines[0]
    pending = conversations.get(chat_id, {})
    
    # Process Line
    ai_res = ask_ai(line, pending, photo_url)
    try:
        parsed = json.loads(ai_res)
    except:
        send_message(chat_id, "Could not map this entry mathematically.")
        return {"ok": True}

    # Product Update Action Path
    if parsed.get("action") == "product_update":
        p_name = parsed.get("product_name")
        if not p_name: 
            send_message(chat_id, "Which product exactly? I need a clear name match.")
            return {"ok": True}
        if supabase:
            res = supabase.table("transactions").select("*").eq("type", "product_master").eq("category", p_name).order("created_at", desc=True).limit(1).execute()
            n = {}
            if res.data:
                try: n = json.loads(res.data[0].get("note", "{}"))
                except: pass
            
            n["selling_price"] = parsed.get("selling_price", n.get("selling_price", 0)) if parsed.get("selling_price") is not None else n.get("selling_price", 0)
            n["cost_price"] = parsed.get("cost_price", n.get("cost_price", 0)) if parsed.get("cost_price") is not None else n.get("cost_price", 0)
            n["stock_qty"] = parsed.get("stock_qty", n.get("stock_qty", 0)) if parsed.get("stock_qty") is not None else n.get("stock_qty", 0)
            
            supabase.table("transactions").insert({
                "type": "product_master",
                "category": p_name,
                "amount": float(n["selling_price"]),
                "note": json.dumps(n),
                "source": "telegram"
            }).execute()
            
            send_message(chat_id, f"Product Configuration Overridden: {p_name}\nSelling Price: {fmt(n['selling_price'])}\nCost Price: {fmt(n['cost_price'])}\nStock: {n['stock_qty']}")
        return {"ok": True}

    conversations[chat_id] = parsed

    if not parsed.get("is_complete") and len(lines) == 1:
        if not parsed.get("amount"): send_message(chat_id, "What represents the amount?")
        elif not parsed.get("type"): send_message(chat_id, "Is this tagged as an Expense, Income, or Liability constraint?")
        elif not parsed.get("category"): send_message(chat_id, "Which specific business category?")
        else: send_message(chat_id, "Please supply missing critical contexts.")
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
    if parsed.get("ca_note"): reply_str += f"\n\nCA Note:\n{parsed.get('ca_note')}"

    send_message(chat_id, reply_str)
    return {"ok": True}