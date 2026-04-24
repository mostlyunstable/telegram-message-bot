"""
Static config loader that reads from config.json.
This replaces the old vulnerable auto-generated config.py.
"""
import json
import os

CONFIG_FILE = "config.json"

# Defaults
_config = {
    "api_id": "",
    "api_hash": "",
    "phones": "",
    "source_channel": "",
    "targets": "",
    "min_delay": 600,
    "max_delay": 900
}

if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r") as f:
        try:
            loaded = json.load(f)
            _config.update(loaded)
        except json.JSONDecodeError:
            pass

# Parse Accounts
ACCOUNTS = []
phone_list = [p.strip() for p in _config["phones"].split("\n") if p.strip()]
account_targets_dict = _config.get("account_targets", {})

for i, phone in enumerate(phone_list):
    p_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
    try:
        api_id = int(_config["api_id"])
    except (ValueError, TypeError):
        api_id = 0
        
    # Parse individual targets
    raw_targets = account_targets_dict.get(phone, "")
    targets_list = [t.strip() for t in raw_targets.replace("\r\n", "\n").replace("\r", "\n").split("\n") if t.strip()]
        
    ACCOUNTS.append({
        "name": f"Account_{i+1}",
        "api_id": api_id,
        "api_hash": _config["api_hash"],
        "phone": phone,
        "session_name": f"sessions/session_{p_clean}",
        "targets": targets_list
    })

MOCK_MODE = False
SOURCE_CHANNEL = _config["source_channel"]

# If source channel is numeric string (like "-100123..."), convert to int.
# Otherwise keep as string (username).
if isinstance(SOURCE_CHANNEL, str) and SOURCE_CHANNEL.lstrip('-').isdigit():
    SOURCE_CHANNEL = int(SOURCE_CHANNEL)

MIN_DELAY = int(_config["min_delay"])
MAX_DELAY = int(_config["max_delay"])
TARGETS_FILE = "targets.txt"
LOG_FILE = "bot.log"
