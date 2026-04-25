import os
import signal
import sys
from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS
from api.routes import register_routes, bot_manager, run_async
from utils.logger import logger

# Initialize Flask
app = Flask(__name__)
# UNIFIED SECRET KEY
app.secret_key = os.environ.get("SECRET_KEY", "ARMEDIAS_PROD_STABLE_2026")

# Enable CORS
CORS(app)

# Initialize SocketIO with production-optimized settings
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode="threading",
    ping_timeout=60,
    ping_interval=25
)

# Register modular routes
register_routes(app, socketio)

def graceful_shutdown(sig, frame):
    """Ensures all Telegram sessions are closed properly on exit."""
    logger.info("🛑 Shutdown signal received. Closing all sessions...")
    try:
        run_async(bot_manager.shutdown())
        logger.info("✅ All sessions closed. Exiting.")
    except Exception as e:
        logger.error(f"⚠️ Error during shutdown: {e}")
    sys.exit(0)

# Register signals for production stability
signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    
    # Create necessary directories
    for d in ["sessions", "logs"]:
        if not os.path.exists(d): os.makedirs(d)
        
    logger.info(f"🚀 ARMEDIAS AI Hub starting on http://localhost:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
