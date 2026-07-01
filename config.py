"""
config.py — Load environment variables
"""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
ALLOWED_USER_IDS = [int(x.strip()) for x in os.getenv("ALLOWED_USER_IDS", "0").split(",") if x.strip()]
ANTIGRAVITY_BRAIN_DIR = os.getenv(
    "ANTIGRAVITY_BRAIN_DIR",
    r"C:\Users\user\.gemini\antigravity-ide\brain"
)
POLLING_INTERVAL = float(os.getenv("POLLING_INTERVAL", "0.5"))
PROJECT_DIR = os.getenv("PROJECT_DIR", r"C:\Projek\Cpulse_package")

import json
NINEROUTER_ACCOUNTS_RAW = os.getenv("NINEROUTER_ACCOUNTS", "")
NINEROUTER_ACCOUNTS = None
if NINEROUTER_ACCOUNTS_RAW:
    try:
        NINEROUTER_ACCOUNTS = json.loads(NINEROUTER_ACCOUNTS_RAW)
    except Exception:
        pass

if not BOT_TOKEN or BOT_TOKEN.startswith("7xxx"):
    raise ValueError("BOT_TOKEN belum diisi di file .env!")

if CHAT_ID == 0:
    raise ValueError("CHAT_ID belum diisi di file .env!")
