# ============================================================
#   TELEGRAM BULK MESSENGER - Configuration
# ============================================================

MOCK_MODE = False

# ----- SENDER ACCOUNTS -----
# Add your API details here
ACCOUNTS = [
    {
        "name": "Account_1",
        "api_id": 12345678,           # Replace with your API ID
        "api_hash": "YOUR_API_HASH",   # Replace with your API Hash
        "phone": "+91XXXXXXXXXX",      # Replace with your Phone Number
        "session_name": "sessions/account_1"
    }
]

# ----- SOURCE CHANNEL -----
# The username or numeric ID of the channel to monitor
SOURCE_CHANNEL = -100123456789

# ----- DELAY SETTINGS (seconds) -----
# randomized delay between messages (recommended 600-900)
MIN_DELAY = 600   
MAX_DELAY = 900  

# ----- TARGET USERS FILE -----
TARGETS_FILE = "targets.txt"

# ----- LOGGING -----
LOG_FILE = "bot.log"
