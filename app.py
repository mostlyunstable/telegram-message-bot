import os
import json
import subprocess
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
        "api_id": "", "api_hash": "", "phone": "",
        "source_channel": "", "targets": "",
        "min_delay": 600, "max_delay": 900
    }

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    with open("targets.txt", "w") as f:
        f.write(config["targets"])
    with open("config.py", "w") as f:
        # We handle source_channel carefully (if it's digits, it's an ID)
        sc = config['source_channel']
        if sc.lstrip('-').isdigit():
            sc_val = sc
        else:
            sc_val = f"'{sc}'"
            
        f.write(f"""# AUTO-GENERATED CONFIG
MOCK_MODE = False
ACCOUNTS = [{{
    "name": "Admin_Account",
    "api_id": {config['api_id'] or 0},
    "api_hash": "{config['api_hash']}",
    "phone": "{config['phone']}",
    "session_name": "sessions/admin_session"
}}]
SOURCE_CHANNEL = {sc_val}
MIN_DELAY = {config['min_delay']}
MAX_DELAY = {config['max_delay']}
TARGETS_FILE = "targets.txt"
LOG_FILE = "bot.log"
""")

@app.route("/")
def index():
    config = load_config()
    # Check if bot process is actually alive
    global BOT_PROCESS
    is_running = False
    if BOT_PROCESS and BOT_PROCESS.poll() is None:
        is_running = True
    else:
        BOT_PROCESS = None
        
    return render_template("index.html", config=config, bot_running=is_running)

@app.route("/save", methods=["POST"])
def save():
    try:
        config = {
            "api_id": request.form.get("api_id"),
            "api_hash": request.form.get("api_hash"),
            "phone": request.form.get("phone"),
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
def start_bot():
    global BOT_PROCESS
    if BOT_PROCESS and BOT_PROCESS.poll() is None:
        return jsonify({"status": "error", "message": "Bot is already running!"})
    
    try:
        # Start the bot. We don't capture stdout here to avoid pipe-clogging.
        # The bot writes to its own log file which we read.
        BOT_PROCESS = subprocess.Popen([sys.executable, "main.py"], 
                                      creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
        return jsonify({"status": "success", "message": "Bot launched in a new window!"})
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
            return jsonify({"status": "success", "message": "Bot terminated."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    return jsonify({"status": "error", "message": "Bot is not running."})

@app.route("/logs")
def get_logs():
    log_path = "logs/bot.log"
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                return "".join(f.readlines()[-30:])
        except: return "Reading logs..."
    return "Bot is ready. Click Start to begin."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
