import os
import time
import asyncio
import threading
import traceback
import jwt
import datetime
from functools import wraps
from flask import render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

from utils.logger import logger
from core.services.config_service import config_service
from core.bot_manager import BotManager
from pyrogram import Client
from pyrogram.errors import (
    AuthKeyUnregistered, PhoneCodeInvalid, PhoneCodeExpired, 
    SessionPasswordNeeded, FloodWait
)

# ──────────────────────────────────────────────
# GLOBAL STATE & SECURITY
# ──────────────────────────────────────────────
bot_manager = BotManager()
_BOT_LOOP = asyncio.new_event_loop()
SECRET_KEY = os.environ.get("SECRET_KEY", "armedias-ai-ultra-secret-2026")

def _run_bot_loop():
    asyncio.set_event_loop(_BOT_LOOP)
    _BOT_LOOP.run_forever()

threading.Thread(target=_run_bot_loop, daemon=True).start()

def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, _BOT_LOOP).result()

def _init_app():
    time.sleep(1)
    run_async(bot_manager.initialize())

threading.Thread(target=_init_app, daemon=True).start()

# ──────────────────────────────────────────────
# AUTH DECORATORS (JWT + SESSION)
# ──────────────────────────────────────────────
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
_ADMIN_PASS_HASH = generate_password_hash(os.environ.get("ADMIN_PASS", "telegram2026"))

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # Check for Authorization header
        if "Authorization" in request.headers:
            token = request.headers["Authorization"].split(" ")[1]
        # Fallback to session for simple page loads
        if not token and "logged_in" in session:
            return f(*args, **kwargs)
            
        if not token:
            return jsonify({"status": "error", "message": "Token missing"}), 401
            
        try:
            jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid or expired token"}), 401
            
        return f(*args, **kwargs)
    return decorated

# ──────────────────────────────────────────────
# ROUTES DEFINITION
# ──────────────────────────────────────────────
def register_routes(app, socketio):

    @app.route("/")
    def index():
        # The frontend will check localStorage and redirect to login if missing
        return render_template("index.html", config=config_service.load())

    @app.route("/login", methods=["GET", "POST"])
    def login():
        # Keep GET for the template, use /api/login for the actual JWT flow
        return render_template("login.html")

    @app.route("/api/login", methods=["POST"])
    def api_login():
        data = request.get_json() or {}
        username = data.get("username")
        password = data.get("password")
        
        if username == ADMIN_USER and check_password_hash(_ADMIN_PASS_HASH, password):
            token = jwt.encode({
                "user": username,
                "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
            }, SECRET_KEY, algorithm="HS256")
            session["logged_in"] = True # Secondary fallback
            return jsonify({"status": "success", "token": token})
        
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401

    @app.route("/api/session/start", methods=["POST"])
    @token_required
    def session_start():
        data = request.get_json() or {}
        phone = data.get("phone")
        worker = bot_manager.get_worker(phone)
        if not worker: return jsonify({"status": "error", "message": "Session not found"}), 404
        success, msg = run_async(worker.start())
        if not success: return jsonify({"status": "error", "message": msg}), 400
        config_service.update_account(phone, "is_loop_active", True)
        return jsonify({"status": "success", "message": "Loop started"})

    @app.route("/api/session/stop", methods=["POST"])
    @token_required
    def session_stop():
        phone = (request.get_json() or {}).get("phone")
        worker = bot_manager.get_worker(phone)
        if not worker: return jsonify({"status": "error", "message": "Not Found"}), 404
        run_async(worker.stop())
        config_service.update_account(phone, "is_loop_active", False)
        return jsonify({"status": "success"})

    @app.route("/api/session/dispatch", methods=["POST"])
    @token_required
    def session_dispatch():
        phone = (request.get_json() or {}).get("phone")
        worker = bot_manager.get_worker(phone)
        if not worker: return jsonify({"status": "error", "message": "Not Found"}), 404
        if not worker.current_msg_id: return jsonify({"status": "error", "message": "No source tracked"}), 400
        success = run_async(worker.trigger_dispatch(worker.current_from_chat, worker.current_msg_id))
        return jsonify({"status": "success", "message": "Manual dispatch enqueued"}) if success else jsonify({"status": "error", "message": "Dispatch failed"}), 400

    @app.route("/api/session/settings", methods=["POST"])
    @token_required
    def session_settings():
        data = request.get_json() or {}
        phone = data.get("phone")
        worker = bot_manager.get_worker(phone)
        p_clean = "".join(filter(str.isdigit, str(phone)))
        config = config_service.load()
        settings = config.setdefault("account_settings", {}).setdefault(p_clean, {})
        settings.update({
            "source_channel": data.get("source_channel"), "loop_interval": int(data.get("loop_interval", 15)), 
            "targets": data.get("targets", []), "msg_delay": int(data.get("msg_delay", 5))
        })
        config_service.save(config)
        if worker: run_async(worker.update_settings(data.get("source_channel"), int(data.get("loop_interval", 15)), data.get("targets", []), int(data.get("msg_delay", 5))))
        return jsonify({"status": "success"})

    @app.route("/save-global", methods=["POST"])
    @token_required
    def save_global():
        config = config_service.load()
        config.update({
            "api_id": request.form.get("api_id", "").strip(),
            "api_hash": request.form.get("api_hash", "").strip(),
            "source_channel": request.form.get("source_channel", "").strip(),
            "loop_interval": int(request.form.get("loop_interval", 15)),
            "msg_delay": int(request.form.get("msg_delay", 5))
        })
        config_service.save(config)
        return jsonify({"status": "success"})

    @app.route("/api/add-account", methods=["POST"])
    @token_required
    def add_account():
        data = request.get_json() or {}
        phone = data.get("phone", "").strip()
        if not phone: return jsonify({"status": "error", "message": "Phone required"}), 400
        p_clean = "".join(filter(str.isdigit, phone))
        config = config_service.load()
        phones_list = [p.strip() for p in config.get("phones", "").split("\n") if p.strip()]
        if any("".join(filter(str.isdigit, p)) == p_clean for p in phones_list): return jsonify({"status": "error", "message": "Phone exists"}), 409
        phones_list.append(phone)
        config["phones"] = "\n".join(phones_list)
        config.setdefault("account_settings", {})[p_clean] = {"source_channel": config.get("source_channel", ""), "loop_interval": config.get("loop_interval", 15), "targets": [], "msg_delay": config.get("msg_delay", 5)}
        config_service.save(config)
        run_async(bot_manager.initialize())
        return jsonify({"status": "success"})

    async def _cleanup_reauth(phone: str):
        p_clean = "".join(filter(str.isdigit, phone))
        worker = bot_manager.get_worker(phone)
        if worker:
            await worker.stop()
            try: await asyncio.wait_for(worker.client.stop(), timeout=3.0)
            except: pass
            bot_manager.workers.pop(p_clean, None)
        base = f"sessions/session_{p_clean}"
        for ext in [".session", ".session-journal"]:
            if os.path.exists(f"{base}{ext}"):
                try: os.remove(f"{base}{ext}")
                except: pass

    @app.route("/api/logout-account", methods=["POST"])
    @token_required
    def logout_account():
        phone = (request.get_json() or {}).get("phone", "").strip()
        run_async(_cleanup_reauth(phone))
        return jsonify({"status": "success"})

    @app.route("/api/delete-account", methods=["POST"])
    @token_required
    def delete_account():
        phone = (request.get_json() or {}).get("phone", "").strip()
        p_clean = "".join(filter(str.isdigit, phone))
        run_async(_cleanup_reauth(phone))
        config = config_service.load()
        phones = [p.strip() for p in config.get("phones", "").split("\n") if p.strip()]
        new_phones = [p for p in phones if "".join(filter(str.isdigit, p)) != p_clean]
        config["phones"] = "\n".join(new_phones)
        config.get("account_settings", {}).pop(p_clean, None)
        config_service.save(config)
        return jsonify({"status": "success"})

    @app.route("/api/account-targets", methods=["GET"])
    @token_required
    def get_targets():
        phone = request.args.get("phone", "").strip()
        p_clean = "".join(filter(str.isdigit, phone))
        config = config_service.load()
        settings = config.get("account_settings", {}).get(p_clean, {})
        targets = settings.get("targets", [])
        return jsonify({"status": "success", "targets": "\n".join(targets) if targets else ""})

    @app.route("/logs")
    @token_required
    def get_logs():
        try:
            with open("logs/bot.log", "r", errors="replace") as f:
                return "".join(f.readlines()[-100:])
        except: return "No logs found."

    def _status_worker():
        while True:
            try:
                config = config_service.load()
                active_workers = bot_manager.get_all_status()
                phones_list = [p.strip() for p in config.get("phones", "").split("\n") if p.strip()]
                processed = []
                final_list = []
                for w in active_workers:
                    w["authenticated"] = True
                    final_list.append(w)
                    processed.append(w["clean_phone"])
                for p in phones_list:
                    p_clean = "".join(filter(str.isdigit, p))
                    if p_clean not in processed:
                        final_list.append({
                            "phone": p, "clean_phone": p_clean, "authenticated": False,
                            "state": "unauth", "sent": 0, "errors": 0, "total": 0, "progress": 0, "last_action": "Login Required"
                        })
                socketio.emit("status_update", {"accounts": final_list})
            except Exception as e: logger.error(f"Broadcaster error: {e}")
            time.sleep(2)

    threading.Thread(target=_status_worker, daemon=True).start()

    # OTP Flow
    _AUTH_CLIENTS = {}
    @app.route("/api/auth/send_code", methods=["POST"])
    @token_required
    def send_otp():
        # Note: Frontend sends this as application/json now for JWT consistency
        data = request.get_json() or {}
        phone = data.get("phone")
        api_id = data.get("api_id", "").strip()
        api_hash = data.get("api_hash", "").strip()
        p_clean = "".join(filter(str.isdigit, str(phone)))
        
        if not api_id or not api_hash:
            return jsonify({"status": "error", "message": "API Credentials missing"}), 400

        async def _logic():
            await _cleanup_reauth(phone)
            client = Client(f"sessions/session_{p_clean}", api_id=int(api_id), api_hash=api_hash, workdir=".", device_model="iPhone 15 Pro Max")
            await client.connect()
            sent = await client.send_code(phone)
            _AUTH_CLIENTS[p_clean] = client
            return {"status": "success", "phone_code_hash": sent.phone_code_hash}
            
        try: return jsonify(run_async(_logic()))
        except Exception as e: return jsonify({"status": "error", "message": str(e)})

    @app.route("/api/auth/sign_in", methods=["POST"])
    @token_required
    def sign_in_otp():
        data = request.get_json() or {}
        phone = data.get("phone")
        p_clean = "".join(filter(str.isdigit, str(phone)))
        code = data.get("code", "").strip()
        
        client = _AUTH_CLIENTS.get(p_clean)
        if not client: return jsonify({"status": "error", "message": "Auth session expired"}), 400
        
        async def _logic():
            try:
                await client.sign_in(phone, data.get("phone_code_hash"), code)
                await asyncio.sleep(1)
                await client.disconnect()
                _AUTH_CLIENTS.pop(p_clean, None)
                await bot_manager.initialize()
                return {"status": "success", "message": "Authenticated"}
            except (PhoneCodeInvalid, PhoneCodeExpired):
                return {"status": "error", "message": "Invalid OTP code"}
            except Exception as e:
                return {"status": "error", "message": str(e)}
            
        try: return jsonify(run_async(_logic()))
        except Exception as e: return jsonify({"status": "error", "message": str(e)})
