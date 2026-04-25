import os
import time
import asyncio
import threading
from functools import wraps
from flask import render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

from utils.logger import logger
from utils.config_loader import load_config, save_config, update_account_setting
from core.bot_manager import BotManager
from pyrogram import Client

# ──────────────────────────────────────────────
# GLOBAL STATE
# ──────────────────────────────────────────────
bot_manager = BotManager()
_BOT_LOOP = asyncio.new_event_loop()

def _run_bot_loop():
    asyncio.set_event_loop(_BOT_LOOP)
    _BOT_LOOP.run_forever()

threading.Thread(target=_run_bot_loop, daemon=True).start()

def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, _BOT_LOOP).result()

# Initialize workers on start
def _init_app():
    run_async(bot_manager.initialize())
threading.Thread(target=_init_app, daemon=True).start()

# ──────────────────────────────────────────────
# AUTH DECORATOR
# ──────────────────────────────────────────────
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
_ADMIN_PASS_HASH = generate_password_hash(os.environ.get("ADMIN_PASS", "telegram2026"))

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "logged_in" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"status": "error", "message": "Unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ──────────────────────────────────────────────
# ROUTES DEFINITION
# ──────────────────────────────────────────────
def register_routes(app, socketio):

    @app.route("/")
    @login_required
    def index():
        return render_template("index.html", config=load_config())

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if request.form.get("username") == ADMIN_USER and check_password_hash(_ADMIN_PASS_HASH, request.form.get("password")):
                session["logged_in"] = True
                return redirect(url_for("index"))
            return render_template("login.html", error="Invalid credentials.")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.pop("logged_in", None)
        return redirect(url_for("login"))

    # Session APIs
    @app.route("/api/session/start", methods=["POST"])
    @login_required
    def session_start():
        phone = (request.get_json() or {}).get("phone")
        worker = bot_manager.get_worker(phone)
        if not worker: return jsonify({"status": "error", "message": "Not found"}), 404
        worker.start()
        update_account_setting(phone, "is_loop_active", True)
        return jsonify({"status": "success"})

    @app.route("/api/session/stop", methods=["POST"])
    @login_required
    def session_stop():
        phone = (request.get_json() or {}).get("phone")
        worker = bot_manager.get_worker(phone)
        if not worker: return jsonify({"status": "error", "message": "Not found"}), 404
        worker.stop()
        update_account_setting(phone, "is_loop_active", False)
        return jsonify({"status": "success"})

    @app.route("/api/session/dispatch", methods=["POST"])
    @login_required
    def session_dispatch():
        phone = (request.get_json() or {}).get("phone")
        worker = bot_manager.get_worker(phone)
        if not worker: return jsonify({"status": "error", "message": "Not found"}), 404
        if not worker.current_msg_id:
            return jsonify({"status": "error", "message": "No source message tracked"}), 400
        run_async(worker.trigger_dispatch(worker.current_from_chat, worker.current_msg_id))
        return jsonify({"status": "success"})

    @app.route("/api/session/settings", methods=["POST"])
    @login_required
    def session_settings():
        data = request.get_json() or {}
        phone = data.get("phone")
        worker = bot_manager.get_worker(phone)
        if not worker: return jsonify({"status": "error", "message": "Not found"}), 404
        
        source = data.get("source_channel")
        interval = int(data.get("loop_interval", 15))
        targets = data.get("targets", [])
        
        worker.update_settings(source, interval, targets)
        
        config = load_config()
        p_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
        settings = config.setdefault("account_settings", {}).setdefault(p_clean, {})
        settings.update({"source_channel": source, "loop_interval": interval, "targets": targets})
        save_config(config)
        return jsonify({"status": "success"})

    @app.route("/save-global", methods=["POST"])
    @login_required
    def save_global():
        config = load_config()
        config.update({
            "api_id": request.form.get("api_id", "").strip(),
            "api_hash": request.form.get("api_hash", "").strip(),
            "source_channel": request.form.get("source_channel", "").strip(),
            "loop_interval": int(request.form.get("loop_interval", 15))
        })
        save_config(config)
        return jsonify({"status": "success"})

    @app.route("/api/add-account", methods=["POST"])
    @login_required
    def add_account():
        phone = (request.get_json() or {}).get("phone", "").strip()
        if not phone: return jsonify({"status": "error", "message": "Empty phone"}), 400
        config = load_config()
        phones = [p.strip() for p in config.get("phones", "").split("\n") if p.strip()]
        if phone in phones: return jsonify({"status": "error", "message": "Exists"}), 409
        phones.append(phone)
        config["phones"] = "\n".join(phones)
        save_config(config)
        return jsonify({"status": "success"})

    @app.route("/api/delete-account", methods=["POST"])
    @login_required
    def delete_account():
        phone = (request.get_json() or {}).get("phone", "").strip()
        p_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
        worker = bot_manager.get_worker(phone)
        if worker:
            worker.stop()
            run_async(worker.client.stop())
            bot_manager.workers.remove(worker)
        
        for ext in [".session", ".session-journal"]:
            path = f"sessions/session_{p_clean}{ext}"
            if os.path.exists(path): os.remove(path)
            
        config = load_config()
        phones = [p.strip() for p in config.get("phones", "").split("\n") if p.strip()]
        if phone in phones: phones.remove(phone)
        config["phones"] = "\n".join(phones)
        config.get("account_settings", {}).pop(p_clean, None)
        save_config(config)
        return jsonify({"status": "success"})

    @app.route("/api/account-targets", methods=["GET"])
    @login_required
    def get_targets():
        phone = request.args.get("phone", "").strip()
        p_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
        config = load_config()
        settings = config.get("account_settings", {}).get(p_clean, {})
        targets = settings.get("targets", [])
        if not targets:
             targets_str = config.get("targets", "")
        else:
             targets_str = "\n".join(targets)
        return jsonify({"status": "success", "targets": targets_str})

    @app.route("/logs")
    @login_required
    def get_logs():
        try:
            with open("logs/bot.log", "r", errors="replace") as f:
                return "".join(f.readlines()[-100:])
        except: return "No logs found."

    # ──────────────────────────────────────────────
    # BROADCASTER
    # ──────────────────────────────────────────────
    def _status_worker():
        while True:
            try:
                config = load_config()
                active_workers = bot_manager.get_all_status()
                phones = [p.strip() for p in config.get("phones", "").split("\n") if p.strip()]
                
                final_list = []
                processed = []
                for w in active_workers:
                    w["authenticated"] = True
                    final_list.append(w)
                    processed.append(w["phone"])
                
                for p in phones:
                    if p not in processed:
                        p_clean = p.replace("+", "").replace(" ", "").replace("-", "")
                        final_list.append({
                            "phone": p, "clean_phone": p_clean, "authenticated": False,
                            "state": "unauth", "sent": 0, "errors": 0, "last_action": "Requires Login"
                        })
                
                socketio.emit("status_update", {"accounts": final_list})
            except Exception as e:
                logger.error(f"Status emit error: {e}")
            time.sleep(2)

    threading.Thread(target=_status_worker, daemon=True).start()

    # OTP Logic
    _AUTH_CLIENTS = {}

    @app.route("/api/auth/send_code", methods=["POST"])
    @login_required
    def send_otp():
        f = request.form
        phone = f.get("phone")
        p_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
        
        async def _logic():
            session_name = f"sessions/session_{p_clean}"
            if os.path.exists(f"{session_name}.session"): os.remove(f"{session_name}.session")
            client = Client(
                session_name, 
                api_id=int(f.get("api_id")), 
                api_hash=f.get("api_hash"), 
                workdir=".",
                device_model="iPhone 15 Pro Max",
                system_version="iOS 17.5.1",
                app_version="10.14.1",
                lang_code="en"
            )
            await client.connect()
            sent = await client.send_code(phone)
            _AUTH_CLIENTS[p_clean] = client
            return {"status": "success", "phone_code_hash": sent.phone_code_hash}
            
        try: return jsonify(run_async(_logic()))
        except Exception as e: return jsonify({"status": "error", "message": str(e)})

    @app.route("/api/auth/sign_in", methods=["POST"])
    @login_required
    def sign_in_otp():
        f = request.form
        phone = f.get("phone")
        p_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
        client = _AUTH_CLIENTS.get(p_clean)
        if not client: return jsonify({"status": "error", "message": "Expired"}), 400
        
        async def _logic():
            await client.sign_in(phone, f.get("phone_code_hash"), f.get("code"))
            await client.disconnect()
            _AUTH_CLIENTS.pop(p_clean, None)
            await bot_manager.initialize()
            return {"status": "success"}
            
        try: return jsonify(run_async(_logic()))
        except Exception as e: return jsonify({"status": "error", "message": str(e)})
