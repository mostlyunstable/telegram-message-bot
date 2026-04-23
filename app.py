import os
import json
import subprocess
import shutil
import time
import sys
import asyncio
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from pyrogram import Client

app = Flask(__name__)
app.secret_key = "ELYNDOR_SECRET_KEY_123"

# --- AUTHENTICATION ---
ADMIN_USER = "admin"
ADMIN_PASS = "elyndor2026"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

CONFIG_FILE = "config.json"
BOT_PROCESS = None

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {
        "api_id": "", "api_hash": "", 
        "phones": "", 
        "source_channel": "", "targets": "",
        "min_delay": 600, "max_delay": 900
    }

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    
    raw_targets = config["targets"]
    target_lines = [t.strip() for t in raw_targets.replace('\r\n', '\n').replace('\r', '\n').split('\n')]
    clean_targets = [t for t in target_lines if t]
    with open("targets.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(clean_targets) + "\n")
    
    phone_list = [p.strip() for p in config['phones'].split('\n') if p.strip()]
    accounts_code = []
    for i, phone in enumerate(phone_list):
        p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
        accounts_code.append(f"""    {{
        "name": "Account_{i+1}",
        "api_id": {config['api_id'] or 0},
        "api_hash": "{config['api_hash']}",
        "phone": "{phone}",
        "session_name": "sessions/session_{p_clean}"
    }}""")
    
    accounts_str = ",\n".join(accounts_code)
    sc = config['source_channel']
    sc_val = sc if sc.lstrip('-').isdigit() else f"'{sc}'"

    with open("config.py", "w") as f:
        f.write(f"""# AUTO-GENERATED CONFIG - {time.ctime()}
MOCK_MODE = False
ACCOUNTS = [
{accounts_str}
]
SOURCE_CHANNEL = {sc_val}
MIN_DELAY = {config['min_delay']}
MAX_DELAY = {config['max_delay']}
TARGETS_FILE = "targets.txt"
LOG_FILE = "bot.log"
""")

# --- ASYNC HELPERS ---
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def async_send_code(api_id, api_hash, phone):
    p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    session_name = f"sessions/session_{p_clean}"
    client = Client(
        session_name, 
        api_id=int(api_id), 
        api_hash=api_hash, 
        workdir=".",
        device_model="iPhone 15 Pro Max",
        system_version="iOS 17.5.1",
        app_version="10.14.1",
        lang_code="en"
    )
    await client.connect()
    try:
        sent_code = await client.send_code(phone)
        return {"status": "success", "phone_code_hash": sent_code.phone_code_hash}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        await client.disconnect()

async def async_sign_in(api_id, api_hash, phone, phone_code_hash, code):
    p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    session_name = f"sessions/session_{p_clean}"
    client = Client(
        session_name, 
        api_id=int(api_id), 
        api_hash=api_hash, 
        workdir=".",
        device_model="iPhone 15 Pro Max",
        system_version="iOS 17.5.1",
        app_version="10.14.1",
        lang_code="en"
    )
    await client.connect()
    try:
        await client.sign_in(phone, phone_code_hash, code)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        await client.disconnect()

# --- ROUTES ---

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session['logged_in'] = True
            return redirect(url_for('index'))
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route("/")
@login_required
def index():
    config = load_config()
    global BOT_PROCESS
    is_running = BOT_PROCESS and BOT_PROCESS.poll() is None
    
    # Check which accounts need auth
    phone_list = [p.strip() for p in config['phones'].split('\n') if p.strip()]
    auth_status = []
    os.makedirs("sessions", exist_ok=True)
    for p in phone_list:
        p_clean = p.replace('+', '').replace(' ', '').replace('-', '')
        session_file = f"sessions/session_{p_clean}.session"
        auth_status.append({
            "phone": p,
            "clean_phone": p_clean,
            "authenticated": os.path.exists(session_file)
        })
        
    return render_template("index.html", config=config, bot_running=is_running, auth_status=auth_status)

@app.route("/api/auth/send_code", methods=["POST"])
@login_required
def api_send_code():
    api_id = request.form.get("api_id")
    api_hash = request.form.get("api_hash")
    phone = request.form.get("phone")
    if not all([api_id, api_hash, phone]):
        return jsonify({"status": "error", "message": "Missing credentials"})
    
    result = run_async(async_send_code(api_id, api_hash, phone))
    return jsonify(result)

@app.route("/api/auth/sign_in", methods=["POST"])
@login_required
def api_sign_in():
    api_id = request.form.get("api_id")
    api_hash = request.form.get("api_hash")
    phone = request.form.get("phone")
    phone_code_hash = request.form.get("phone_code_hash")
    code = request.form.get("code")
    
    if not all([api_id, api_hash, phone, phone_code_hash, code]):
        return jsonify({"status": "error", "message": "Missing required fields"})
        
    result = run_async(async_sign_in(api_id, api_hash, phone, phone_code_hash, code))
    return jsonify(result)

@app.route("/save", methods=["POST"])
@login_required
def save():
    try:
        config = {
            "api_id": request.form.get("api_id"),
            "api_hash": request.form.get("api_hash"),
            "phones": request.form.get("phones"),
            "source_channel": request.form.get("source_channel"),
            "targets": request.form.get("targets"),
            "min_delay": int(request.form.get("min_delay", 600)),
            "max_delay": int(request.form.get("max_delay", 900))
        }
        save_config(config)
        return jsonify({"status": "success", "message": "Configuration saved!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/start", methods=["POST"])
@login_required
def start_bot():
    global BOT_PROCESS
    if BOT_PROCESS and BOT_PROCESS.poll() is None:
        return jsonify({"status": "error", "message": "Bot is already running!"})
    
    try:
        if os.path.exists("__pycache__"): shutil.rmtree("__pycache__")
        if os.path.exists("logs/bot.log"):
            try: os.remove("logs/bot.log")
            except: pass
            
        # We don't need CREATE_NEW_CONSOLE anymore because it won't prompt!
        BOT_PROCESS = subprocess.Popen([sys.executable, "main.py"])
        return jsonify({"status": "success", "message": "Automation started in background!"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Launch failed: {e}"})

@app.route("/stop", methods=["POST"])
@login_required
def stop_bot():
    global BOT_PROCESS
    if BOT_PROCESS:
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(BOT_PROCESS.pid)], capture_output=True)
            else:
                BOT_PROCESS.terminate()
            BOT_PROCESS = None
            return jsonify({"status": "success", "message": "All automation stopped."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    return jsonify({"status": "error", "message": "Bot is not running."})

@app.route("/clear_sessions", methods=["POST"])
@login_required
def clear_sessions():
    if os.path.exists("sessions"):
        shutil.rmtree("sessions")
        os.makedirs("sessions", exist_ok=True)
        return jsonify({"status": "success", "message": "All session files cleared!"})
    return jsonify({"status": "success", "message": "No sessions to clear."})

@app.route("/logs")
@login_required
def get_logs():
    log_path = "logs/bot.log"
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                return "".join(f.readlines()[-30:])
        except: return "Initializing..."
    return "Ready. Waiting for first message..."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
