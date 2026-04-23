import os
import json
import subprocess
import shutil
import time
import sys
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CONFIG_FILE = "config.json"
BOT_PROCESS = None

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {
        "api_id": "", "api_hash": "", 
        "phones": "", # Support multiple phones
        "source_channel": "", "targets": "",
        "min_delay": 600, "max_delay": 900
    }

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    
    # Target normalization
    raw_targets = config["targets"]
    target_lines = [t.strip() for t in raw_targets.replace('\r\n', '\n').replace('\r', '\n').split('\n')]
    clean_targets = [t for t in target_lines if t]
    with open("targets.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(clean_targets) + "\n")
    
    # Process multiple phones
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

@app.route("/")
def index():
    config = load_config()
    global BOT_PROCESS
    is_running = BOT_PROCESS and BOT_PROCESS.poll() is None
    return render_template("index.html", config=config, bot_running=is_running)

@app.route("/save", methods=["POST"])
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
        return jsonify({"status": "success", "message": "Global Configuration Saved!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/start", methods=["POST"])
def start_bot():
    global BOT_PROCESS
    if BOT_PROCESS and BOT_PROCESS.poll() is None:
        return jsonify({"status": "error", "message": "Bot is already running!"})
    
    try:
        # Cleanup cache
        if os.path.exists("__pycache__"): shutil.rmtree("__pycache__")
        
        # Clear log for clean session
        if os.path.exists("logs/bot.log"):
            try: os.remove("logs/bot.log")
            except: pass
            
        BOT_PROCESS = subprocess.Popen([sys.executable, "main.py"], 
                                      creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
        return jsonify({"status": "success", "message": "Automation started with all accounts!"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Launch failed: {e}"})

@app.route("/stop", methods=["POST"])
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
def clear_sessions():
    if os.path.exists("sessions"):
        shutil.rmtree("sessions")
        os.makedirs("sessions", exist_ok=True)
        return jsonify({"status": "success", "message": "All session files cleared!"})
    return jsonify({"status": "success", "message": "No sessions to clear."})

@app.route("/logs")
def get_logs():
    log_path = "logs/bot.log"
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                return "".join(f.readlines()[-30:])
        except: return "Initializing..."
    return "Ready. Waiting for first message..."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
