import os
import json
import subprocess
import signal
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__)

CONFIG_FILE = "config.json"
BOT_PROCESS = None

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {
        "api_id": "",
        "api_hash": "",
        "phone": "",
        "source_channel": "",
        "targets": "",
        "min_delay": 600,
        "max_delay": 900
    }

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    
    # Also sync with targets.txt
    with open("targets.txt", "w") as f:
        f.write(config["targets"])
    
    # Sync with config.py (overwriting it for the bot to read)
    with open("config.py", "w") as f:
        f.write(f"""# AUTO-GENERATED CONFIG
MOCK_MODE = False
ACCOUNTS = [{{
    "name": "Admin_Account",
    "api_id": {config['api_id'] or 0},
    "api_hash": "{config['api_hash']}",
    "phone": "{config['phone']}",
    "session_name": "sessions/admin_session"
}}]
SOURCE_CHANNEL = "{config['source_channel']}"
MIN_DELAY = {config['min_delay']}
MAX_DELAY = {config['max_delay']}
TARGETS_FILE = "targets.txt"
LOG_FILE = "bot.log"
""")

@app.route("/")
def index():
    config = load_config()
    return render_template("index.html", config=config, bot_running=(BOT_PROCESS is not None))

@app.route("/save", methods=["POST"])
def save():
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

@app.route("/start", methods=["POST"])
def start_bot():
    global BOT_PROCESS
    if BOT_PROCESS is None:
        # Start the bot as a background process
        # Use sys.executable to ensure we use the same python
        import sys
        BOT_PROCESS = subprocess.Popen([sys.executable, "main.py"], 
                                      stdout=subprocess.PIPE, 
                                      stderr=subprocess.STDOUT,
                                      text=True)
        return jsonify({"status": "success", "message": "Bot started!"})
    return jsonify({"status": "error", "message": "Bot is already running!"})

@app.route("/stop", methods=["POST"])
def stop_bot():
    global BOT_PROCESS
    if BOT_PROCESS:
        BOT_PROCESS.terminate()
        BOT_PROCESS = None
        return jsonify({"status": "success", "message": "Bot stopped!"})
    return jsonify({"status": "error", "message": "Bot is not running!"})

@app.route("/logs")
def get_logs():
    log_path = "logs/bot.log"
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            lines = f.readlines()[-20:] # Get last 20 lines
            return "".join(lines)
    return "No logs available yet..."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
