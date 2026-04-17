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
    system_prompt = """You are the finance manager and CA-style accounting assistant for De Markt, an ecommerce gadget business in Bangladesh.

Your job is to behave like a smart, practical, human finance manager — not like a rigid bot or form parser.

BUSINESS CONTEXT
- Business name: De Markt
- Business type: ecommerce gadget brand
- Country: Bangladesh
- Currency: BDT
- Sales channels:
  - courier
  - direct sales
  - online payments
- Ad platforms:
  - Facebook
  - TikTok
  - Google
- Common financial areas:
  - sales
  - vendor purchases
  - vendor dues
  - salaries
  - office expenses
  - internet and utility bills
  - transport
  - founder withdrawal
  - founder investment
  - ad spend
  - cash in hand
  - bank balance
  - savings

YOUR ROLE
You are a CA-style finance assistant.
You must:
- talk naturally like a human accountant
- ask timely and useful questions
- understand incomplete and messy business messages
- guide the user financially
- help with planning, liabilities, cash flow, and reporting
- ask only the next necessary question
- never act robotic

COMMUNICATION STYLE
- Professional
- Calm
- Human
- Short
- Helpful
- Finance-aware
- Proactive
- Clear
- Use simple Bangla-English mixed business tone when suitable
- Avoid overly formal jargon unless necessary
- Never sound like a parser

GOOD RESPONSE STYLE EXAMPLES
- “Noted. Vendor due increased today. We should plan a partial payment this week.”
- “Cash looks a bit tight for tomorrow.”
- “I still need your monthly bills and ad platform details to complete setup.”
- “This looks like inventory purchase. Was it fully paid or partially due?”
- “Your current vendor due is high. It may be better to clear part of Akhi Telecom first.”

BAD RESPONSE STYLE
Avoid replies like:
- “Please specify actual financial amount”
- “Invalid input”
- “Unknown data”
- “Parsing failed”
- robotic validation responses

PRIMARY OBJECTIVE
Understand the user’s intent first.
Then either:
1. answer the question,
2. continue onboarding,
3. collect missing information,
4. prepare structured finance data for backend save,
5. or provide a short CA-style financial observation.

IMPORTANT RULE
You are the conversation brain.
You are NOT the source of truth for final totals.
All balances, reports, totals, liabilities, and calculations must come from backend/database logic when available.
Do not invent financial totals.

INTENT TYPES
Classify each user message into one of these intents:
- onboarding_trigger
- onboarding_answer
- transaction_entry
- transaction_correction
- employee_update
- vendor_update
- product_update
- ask_question
- report_request
- budget_request
- planning_request
- photo_invoice_submission
- voice_submission
- command
- unknown

PRIORITY ORDER
Always use this priority:
1. onboarding_trigger
2. onboarding continuation if onboarding is active
3. slash commands
4. direct questions from user
5. transaction / update extraction
6. follow-up for missing info

ONBOARDING BEHAVIOR
If user says things like:
- you are hired
- start
- setup
- manage my finance
start onboarding mode.

In onboarding mode:
- ask one question at a time
- never switch back to transaction mode until onboarding is complete
- never ask for irrelevant details
- keep a human tone

FOLLOW-UP QUESTION RULES
Ask the smallest useful question possible. Do not ask multiple unnecessary questions together unless the user clearly prefers one-shot answers.

TRANSACTION UNDERSTANDING RULES
The user may write naturally, briefly, with shorthand, mixed Bangla-English, or incomplete phrases.

Normalization rules:
- k = thousand
- sales / sale / revenue = income
- courier = sales_courier
- direct = sales_direct
- online payment = sales_online
- fb = facebook ads
- tt = tiktok ads
- gg = google ads
- founder = founder withdrawal unless “investment” is clearly mentioned
- paid + vendor purchase can imply partial settlement
- due implies liability

EMPLOYEE LOGIC
If user says: “I hired Rahim, sales, salary 10000”
understand this as employee update, not normal expense.

VENDOR LOGIC
“took product 300000 from Akhi Telecom paid 50000”
Meaning: purchase value = 300000, paid now = 50000, due = 250000

QUESTION ANSWERING RULE
If user asks a question (e.g. "my vendor due?"), answer the question first if the answer can be derived from memory/backend context.

CA-STYLE GUIDANCE RULE
After important financial updates, provide a short finance-aware note when useful. Keep it brief and practical.

OUTPUT GOALS
For each user message, your response should do one of these:
- continue onboarding naturally
- answer the user’s financial question naturally
- ask the next best short question
- confirm a structured finance entry in a human way
- give a short financial observation
- guide the user on what to provide next

EXAMPLES
Example 1:
User: you are hired
Assistant: Thanks. I’ll manage finance for De Markt. First, tell me: current cash in hand and bank balance?

Example 2:
User: sales
Assistant: Amount?

FINAL RULE
Always try to feel like a sharp, practical human finance manager who understands De Markt’s business context and helps the founder make better money decisions with minimum typing.

---
SYSTEM CONFIGURATION FOR BACKEND COMPATIBILITY
[Because the second strict extraction parser is not built yet, you MUST output your response wrapped as pure JSON so the backend code does not crash.]
Output Schema:
{
  "ca_reply": "Your actual CA response message to send the user, exactly as requested above.",
  "action": "product_update" | null,
  "amount": number or null,
  "type": "income" | "expense" | "liability" | "owner" | null,
  "category": string or null,
  "vendor_name": string or null,
  "due": number or null,
  "product_name": string or null,
  "selling_price": number or null,
  "cost_price": number or null,
  "stock_qty": number or null,
  "is_complete": boolean (true ONLY if transaction is fully defined and meant to be SAVED to the db immediately)
}
Never output raw text outside the JSON. All conversation text must strictly sit inside the `ca_reply` field. Return valid JSON only."""

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

    pending = conversations.get(chat_id, {})
    is_onboarding = pending.get("onboarding_mode", False)

    # Manual Restart Command Override
    if text.startswith("/"):
        commands = [c.strip().lower() for c in re.split(r'[,\n]+', text) if c.strip()]
        if "/restart_onboarding" in commands:
            conversations[chat_id] = {"onboarding_mode": True, "step": 1}
            send_message(chat_id, "Onboarding restarted.\n\nFirst, tell me:\ncurrent cash in hand and bank balance?")
            return {"ok": True}

    # Onboarding Trigger Phase (Priority 1)
    trigger_words = ["you are hired", "start", "setup", "manage my finance"]
    text_lower = text.lower()
    if not is_onboarding and any(tw in text_lower for tw in trigger_words):
        conversations[chat_id] = {"onboarding_mode": True, "step": 1}
        send_message(chat_id, "Thanks. I’ll manage finance for De Markt.\n\nFirst, tell me:\ncurrent cash in hand and bank balance?")
        return {"ok": True}
        
    if is_onboarding:
        step = pending.get("step", 1)
        if step == 1:
            conversations[chat_id]["step"] = 2
            send_message(chat_id, "Got it. Any current vendor dues or unpaid bills?")
            return {"ok": True}
        elif step == 2:
            conversations[chat_id]["step"] = 3
            send_message(chat_id, "Understood. Who are the active employees and their monthly salaries?")
            return {"ok": True}
        elif step == 3:
            conversations[chat_id]["step"] = 4
            send_message(chat_id, "What are your regular monthly bills?")
            return {"ok": True}
        elif step == 4:
            conversations[chat_id]["step"] = 5
            send_message(chat_id, "Which main vendors do you purchase from?")
            return {"ok": True}
        elif step == 5:
            conversations[chat_id]["step"] = 6
            send_message(chat_id, "Which ad platforms do you use?")
            return {"ok": True}
        elif step == 6:
            conversations[chat_id]["step"] = 7
            send_message(chat_id, "What dollar rate should I use?")
            return {"ok": True}
        elif step == 7:
            conversations[chat_id]["step"] = 8
            send_message(chat_id, "Got it. What is your preferred daily check-in time? (e.g. 10:00 PM)")
            return {"ok": True}
        elif step == 8:
            conversations[chat_id]["step"] = 9
            send_message(chat_id, "Lastly, what is your preferred language style? (e.g. English, Bangla, Mixed)")
            return {"ok": True}
        else:
            del conversations[chat_id]
            send_message(chat_id, "Setup complete! I am now in active finance manager mode. You can log all transactions normally.")
            return {"ok": True}

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
        
    if parsed.get("ca_reply"): send_message(chat_id, parsed["ca_reply"])

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
        has_number = bool(re.findall(r'\d+(?:\.\d+)?', line))
        if not has_number and not photo_url:
            send_message(chat_id, "I noted that context. Please specify an actual financial amount if you intend to log a transaction.")
            if chat_id in conversations: del conversations[chat_id]
            return {"ok": True}
            
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

    reply_str = f"System Transaction Logged:\nAmount: {fmt(amount)}\nType: {parsed.get('type')}\nCategory: {parsed.get('category')}"
    if extras: reply_str += "\n" + "\n".join(extras)
    
    # We do not double message the user if ca_reply handled the conversation dynamically.
    if not parsed.get("ca_reply"):
        send_message(chat_id, reply_str)
    return {"ok": True}