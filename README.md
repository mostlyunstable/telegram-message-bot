# Telegram Multi-Account Bulk Messenger (Trial Version)

This professional automation tool monitors a source channel and forwards every new post to a list of 200+ target accounts using multiple sender accounts and randomized delays to bypass spam detection.

## 🚀 Setup Instructions

### 1. Installation
Ensure you have Python 3.10+ installed. Then, install the required libraries:
```bash
pip install -r requirements.txt
```

### 2. Telegram API Credentials
You need your own API keys to run the bot:
1. Go to [my.telegram.org](https://my.telegram.org) and log in.
2. Go to "API development tools" and create a new application.
3. Copy your `App api_id` and `App api_hash`.

### 3. Configuration
Open `config.py` and fill in your details:
- `api_id`: Your API ID.
- `api_hash`: Your API Hash.
- `phone`: Your phone number (with country code, e.g., +91...).
- `SOURCE_CHANNEL`: The numeric ID or username of the channel to watch.

### 4. Target List
Open `targets.txt` and paste your list of usernames (one per line, e.g., `@username`).

### 5. Running the Bot
Start the bot by running:
```bash
python main.py
```
On the first run, it will ask for a **Login Code** sent to your Telegram app. Enter it to authorize the session.

---

## 🔒 Trial Version Limitations
This version is for **validation and testing only**.
- Supports up to 5 forwarded messages.
- Includes full round-robin account rotation and delay logic.
- After 5 messages, the license will expire.

**Please contact the developer for the full, unlimited license.**
