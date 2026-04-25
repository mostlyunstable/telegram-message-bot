import os
from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS
from api.routes import register_routes

# Initialize Flask
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ARMEDIAS_PROD_2026")

# Enable CORS for frontend flexibility
CORS(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Register modular routes
register_routes(app, socketio)

if __name__ == "__main__":
    # Standardize on Port 5001 to avoid AirPlay conflicts on macOS
    port = int(os.environ.get("PORT", 5001))
    
    print(f"🚀 ARMEDIAS AI Hub starting on http://localhost:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
