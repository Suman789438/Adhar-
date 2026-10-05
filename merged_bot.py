#!/usr/bin/env python3
"""
Aadhaar Telegram Bot - Render Ready (Fixed)
"""

# ============================================================
# SECTION 1: STANDARD IMPORTS (সবসময় available)
# ============================================================
import os
import sys
import re
import json
import time
import uuid
import base64
import asyncio
import threading
import datetime
import subprocess
import importlib
import shutil
import socketserver
import http.server
from io import BytesIO
from dotenv import load_dotenv
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

load_dotenv()
os.environ['PYTHONIOENCODING'] = 'utf-8'

# ============================================================
# SECTION 2: STARTUP VERIFICATION (আগে চেক, তারপর ইমপোর্ট)
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRACKED_DIR = os.path.join(BASE_DIR, "cracked_aadhar")
os.makedirs(CRACKED_DIR, exist_ok=True)

REQUIRED_MODULES = {
    "telebot": "pyTelegramBotAPI",
    "requests": "requests",
    "urllib3": "urllib3",
    "dotenv": "python-dotenv",
    "fitz": "PyMuPDF",
    "pikepdf": "pikepdf",
    "PIL": "Pillow",
}

OPTIONAL_MODULES = {
    "ddddocr": "ddddocr (Auto-Captcha Solver)",
}

REQUIRED_FILES = {
    "pdf_processor.py": "PDF processing engine",
}


def check_startup_requirements():
    print("=" * 60)
    print("    AADHAAR TELEGRAM BOT - STARTUP VERIFICATION")
    print("=" * 60)

    print("\n📦 Verifying Required Python Packages:")
    print("-" * 60)
    missing_packages = []
    for module_name, pip_name in REQUIRED_MODULES.items():
        try:
            importlib.import_module(module_name)
            print(f"  🟢 {pip_name:<22} -> PRESENT")
        except ImportError:
            print(f"  🔴 {pip_name:<22} -> MISSING")
            missing_packages.append(pip_name)

    print("\n📦 Optional Packages:")
    print("-" * 60)
    for module_name, pip_name in OPTIONAL_MODULES.items():
        try:
            importlib.import_module(module_name)
            print(f"  🟢 {pip_name:<30} -> PRESENT")
        except ImportError:
            print(f"  🟡 {pip_name:<30} -> MISSING (manual captcha fallback)")

    print("\n📂 Verifying Core Files:")
    print("-" * 60)
    missing_files = []
    for file_name, desc in REQUIRED_FILES.items():
        full_path = os.path.join(BASE_DIR, file_name)
        if os.path.exists(full_path):
            print(f"  🟢 {file_name:<22} -> PRESENT ({desc})")
        else:
            print(f"  🔴 {file_name:<22} -> MISSING ({desc})")
            missing_files.append(file_name)

    print("\n🔑 Verifying Environment Variables:")
    print("-" * 60)
    token_found = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    admin_found = bool(os.getenv("ADMIN_IDS"))
    print(f"  {'🟢' if token_found else '🔴'} TELEGRAM_BOT_TOKEN   -> {'CONFIGURED' if token_found else 'MISSING'}")
    print(f"  {'🟢' if admin_found else '🟡'} ADMIN_IDS            -> {'CONFIGURED' if admin_found else 'WARNING (not set)'}")

    print("=" * 60)

    if missing_packages or missing_files or not token_found:
        print("\n❌ STARTUP ERROR: Critical requirements missing!")
        if missing_packages:
            print(f"\n👉 Install: pip install {' '.join(missing_packages)}")
        if missing_files:
            print(f"\n👉 Missing files: {', '.join(missing_files)}")
        if not token_found:
            print("\n👉 Set TELEGRAM_BOT_TOKEN in Render Environment Variables")
        print("=" * 60)
        sys.exit(1)
    print("✨ All requirements met! Starting bot...\n")


check_startup_requirements()

# ============================================================
# SECTION 3: SAFE HEAVY IMPORTS (post-verification)
# ============================================================
import telebot
from telebot import types, apihelper

try:
    import ddddocr
    DDDDOCR_AVAILABLE = True
except Exception as e:
    print(f"⚠️ ddddocr not available: {e}. Manual captcha only mode.")
    DDDDOCR_AVAILABLE = False

# ============================================================
# SECTION 4: CONFIGURATION FROM ENV
# ============================================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN missing! Set it in environment.")
    sys.exit(1)

ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().lstrip("-").isdigit()]

DEVELOPER_USERNAME = os.getenv("DEVELOPER_USERNAME", "@your_username")
if not DEVELOPER_USERNAME.startswith("@"):
    DEVELOPER_USERNAME = "@" + DEVELOPER_USERNAME

FORCE_JOIN_ENABLED = os.getenv("FORCE_JOIN_ENABLED", "False").lower() in ("true", "1", "yes")

REQUIRED_CHANNELS_RAW = os.getenv("REQUIRED_CHANNEL_IDS", "")
REQUIRED_CHANNELS = []
for x in REQUIRED_CHANNELS_RAW.split(","):
    x = x.strip()
    if not x:
        continue
    try:
        REQUIRED_CHANNELS.append(int(x))
    except ValueError:
        REQUIRED_CHANNELS.append(x)

if not FORCE_JOIN_ENABLED:
    REQUIRED_CHANNELS = []

# ============================================================
# SECTION 5: UIDAI API ENDPOINTS
# ============================================================
BASE_URL = "https://tathya.uidai.gov.in"
CAPTCHA_URL = f"{BASE_URL}/audioCaptchaService/api/captcha/v3/generation"
OTP_URL = f"{BASE_URL}/unifiedAppAuthService/api/v2/generate/aadhaar/otp"
DOWNLOAD_URL = f"{BASE_URL}/downloadAadhaarService/api/aadhaar/download"
RETRIEVE_URL = f"{BASE_URL}/retrieveEidUid/ext/v1/generic/retrieveuideid"

# ============================================================
# SECTION 6: STATS MANAGER
# ============================================================
STATS_FILE = os.path.join(BASE_DIR, "stats.json")
ERROR_LOG_FILE = os.path.join(BASE_DIR, "errors.log")
stats_lock = threading.RLock()
error_log_lock = threading.RLock()
last_global_run_time = 0

_DEFAULT_STATS = {
    "total_views": 0, "today_date": "", "today_views": 0,
    "success_count": 0, "fail_count": 0, "mode": "paid",
    "default_credits": 0, "users": [], "cracked_history": [],
    "today_users": [], "cooldown_seconds": 60, "max_concurrent_tasks": 15
}


def load_stats():
    with stats_lock:
        if not os.path.exists(STATS_FILE) or os.path.getsize(STATS_FILE) == 0:
            return _DEFAULT_STATS.copy()
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in _DEFAULT_STATS.items():
                    if k not in data:
                        data[k] = v
                return data
        except Exception as e:
            print(f"⚠️ [STATS] load error: {e}")
            return _DEFAULT_STATS.copy()


def save_stats(data):
    with stats_lock:
        try:
            tmp = STATS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, STATS_FILE)
        except Exception as e:
            print(f"⚠️ [STATS] save error: {e}")


def register_visit(chat_id, username=None, first_name=None):
    with stats_lock:
        data = load_stats()
        today = datetime.date.today().isoformat()
        try:
            str_chat_id = int(chat_id)
        except Exception:
            str_chat_id = chat_id
        if "today_users" not in data:
            data["today_users"] = []
        if data["today_date"] != today:
            data["today_date"] = today
            data["today_views"] = 1
            data["today_users"] = [str_chat_id]
            data["total_views"] += 1
        else:
            if str_chat_id not in data["today_users"]:
                data["today_users"].append(str_chat_id)
                data["today_views"] += 1
                data["total_views"] += 1

        users_list = data.get("users", [])
        updated, seen = [], set()
        for u in users_list:
            if isinstance(u, dict):
                cid = u.get("chat_id")
                if cid not in seen:
                    seen.add(cid)
                    updated.append(u)
            else:
                try:
                    cid = int(u)
                    if cid not in seen:
                        seen.add(cid)
                        updated.append({
                            "chat_id": cid, "first_name": "N/A", "username": "N/A",
                            "joined": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                except Exception:
                    pass

        existing = None
        for u in updated:
            if u["chat_id"] == str_chat_id:
                existing = u
                break
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if existing:
            if first_name and (existing.get("first_name") == "N/A" or existing["first_name"] != first_name):
                existing["first_name"] = first_name
            if username and (existing.get("username") == "N/A" or existing["username"] != username):
                existing["username"] = username
        else:
            updated.append({
                "chat_id": str_chat_id,
                "first_name": first_name or "N/A",
                "username": username or "N/A",
                "joined": now_str,
                "credits": data.get("default_credits", 3)
            })
        data["users"] = updated
        save_stats(data)


def record_success(chat_id, user_info, name, mobile, uid, password, eid=None):
    with stats_lock:
        data = load_stats()
        data["success_count"] += 1
        username = user_info.get("username", "N/A") if user_info else "N/A"
        first_name = user_info.get("first_name", "N/A") if user_info else "N/A"
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "timestamp": now, "chat_id": chat_id, "username": username,
            "first_name": first_name, "name": name, "mobile": mobile,
            "uid": uid, "password": password, "eid": eid or "N/A"
        }
        data["cracked_history"].append(record)
        save_stats(data)
        txt_path = os.path.join(BASE_DIR, "cracked_history.txt")
        try:
            with open(txt_path, "a", encoding="utf-8") as f:
                f.write("=" * 60 + "\n")
                f.write(f"{data['success_count']}. [Timestamp: {now}]\n")
                f.write(f"   👤 Telegram User: {first_name} (@{username}) [ID: {chat_id}]\n")
                f.write(f"   🆔 Holder Name: {name}\n")
                f.write(f"   📞 Mobile: {mobile}\n")
                f.write(f"   🆔 EID: {eid or 'N/A'}\n")
                f.write(f"   🔑 Aadhaar UID: {uid}\n")
                f.write(f"   🔓 Password: {password}\n")
                f.write("=" * 60 + "\n\n")
        except Exception as e:
            print(f"⚠️ write history: {e}")
        try:
            deduct_user_credit(chat_id)
        except Exception:
            pass


def record_failure():
    with stats_lock:
        data = load_stats()
        data["fail_count"] += 1
        save_stats(data)


def get_stats_summary(active_user_states):
    data = load_stats()
    steps = {}
    for uid, st in active_user_states.items():
        step = st.get("step", "IDLE")
        if step != "IDLE":
            steps[step] = steps.get(step, 0) + 1
    active_count = sum(steps.values())
    active_details = ""
    if active_count > 0:
        for step, count in steps.items():
            active_details += f"  ├─ <code>{step:<18}</code>: <b>{count} user(s)</b>\n"
    else:
        active_details = "  └─ <i>No active tasks.</i>\n"
    mode = data.get("mode", "free").upper()
    def_credits = data.get("default_credits", 3)
    cooldown = data.get("cooldown_seconds", 60)
    max_concurrent = data.get("max_concurrent_tasks", 15)
    total_runs = data['success_count'] + data['fail_count']
    success_rate = 100 if total_runs == 0 else int((data['success_count'] / total_runs) * 100)
    total_users = total_groups = 0
    for u in data.get("users", []):
        if isinstance(u, dict):
            cid = u.get("chat_id", 0)
        else:
            try:
                cid = int(u)
            except Exception:
                cid = 0
        if cid > 0:
            total_users += 1
        elif cid < 0:
            total_groups += 1
    return (
        f"<b>ADMINISTRATION DASHBOARD v3.5</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ <b>SYSTEM CONFIGURATION:</b>\n"
        f"  ├─ Bot Mode:       <b>{mode} Mode</b>\n"
        f"  ├─ Def. Credits:   <code>{def_credits}</code>\n"
        f"  ├─ Global Cooldown: <code>{cooldown}s</code>\n"
        f"  └─ Max Concurrency: <code>{max_concurrent}</code>\n\n"
        f"📊 <b>LIVE SYSTEM METRICS:</b>\n"
        f"  ├─ Total Views:      <code>{data['total_views']}</code>\n"
        f"  ├─ Today Views:      <code>{data['today_views']}</code>\n"
        f"  ├─ Total Users:      <code>{total_users}</code>\n"
        f"  ├─ Total Groups:     <code>{total_groups}</code>\n"
        f"  ├─ Registered All:   <code>{len(data['users'])}</code>\n"
        f"  └─ Success Rate:    <b>{success_rate}%</b> (<code>{data['success_count']} ✅</code> / <code>{data['fail_count']} ❌</code>)\n\n"
        f"👥 <b>ACTIVE ROOMS:</b> <code>{active_count} active</code>\n{active_details}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


def get_cracked_data_file_path():
    data = load_stats()
    report_path = os.path.join(BASE_DIR, "cracked_history_report.txt")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("🔒 CRACKED AADHAAR DATABASE REPORT\n")
            f.write(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Successes: {data['success_count']}\n")
            f.write("=" * 60 + "\n\n")
            history = data.get("cracked_history", [])
            if not history:
                f.write("No records.\n")
            else:
                for idx, rec in enumerate(history, 1):
                    f.write("=" * 60 + "\n")
                    f.write(f"{idx}. [Timestamp: {rec.get('timestamp', 'N/A')}]\n")
                    f.write(f"   👤 Telegram User: {rec.get('first_name', 'N/A')} (@{rec.get('username', 'N/A')}) [ID: {rec.get('chat_id', 'N/A')}]\n")
                    f.write(f"   🆔 Holder Name: {rec.get('name', 'N/A')}\n")
                    f.write(f"   📞 Mobile: {rec.get('mobile', 'N/A')}\n")
                    f.write(f"   🆔 EID: {rec.get('eid', 'N/A')}\n")
                    f.write(f"   🔑 Aadhaar UID: {rec.get('uid', 'N/A')}\n")
                    f.write(f"   🔓 Password: {rec.get('password', 'N/A')}\n")
                    f.write("=" * 60 + "\n\n")
        return report_path
    except Exception as e:
        print(f"⚠️ report gen: {e}")
        return None


def log_error(chat_id, user_info, error_msg):
    with error_log_lock:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        username = user_info.get("username", "N/A") if user_info else "N/A"
        first_name = user_info.get("first_name", "N/A") if user_info else "N/A"
        entry = f"[{now}] User: {first_name} (@{username}) [ID: {chat_id}] | Error: {error_msg}\n"
        try:
            with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"⚠️ log error: {e}")


def get_error_log_file_path():
    if os.path.exists(ERROR_LOG_FILE) and os.path.getsize(ERROR_LOG_FILE) > 0:
        return ERROR_LOG_FILE
    return None


# --- Credits & Cooldown ---
def get_bot_mode():
    with stats_lock:
        return load_stats().get("mode", "free")


def set_bot_mode(mode):
    with stats_lock:
        data = load_stats()
        data["mode"] = mode
        save_stats(data)


def get_default_credits():
    with stats_lock:
        return load_stats().get("default_credits", 3)


def set_default_credits(count):
    with stats_lock:
        data = load_stats()
        data["default_credits"] = int(count)
        save_stats(data)


def get_user_credits(chat_id):
    with stats_lock:
        data = load_stats()
        try:
            str_chat_id = int(chat_id)
        except Exception:
            str_chat_id = chat_id
        for u in data.get("users", []):
            if isinstance(u, dict) and u.get("chat_id") == str_chat_id:
                return u.get("credits", 0)
        return 0


def add_user_credits(chat_id, amount):
    with stats_lock:
        data = load_stats()
        try:
            str_chat_id = int(chat_id)
        except Exception:
            str_chat_id = chat_id
        found = False
        new_bal = 0
        for u in data.get("users", []):
            if isinstance(u, dict) and u.get("chat_id") == str_chat_id:
                current = u.get("credits", data.get("default_credits", 3))
                u["credits"] = max(0, current + amount)
                new_bal = u["credits"]
                found = True
                break
        if not found:
            new_bal = max(0, amount)
            data["users"].append({
                "chat_id": str_chat_id, "first_name": "N/A", "username": "N/A",
                "joined": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "credits": new_bal
            })
        save_stats(data)
        return new_bal


def deduct_user_credit(chat_id):
    with stats_lock:
        data = load_stats()
        if data.get("mode", "free") != "paid":
            return
        try:
            str_chat_id = int(chat_id)
        except Exception:
            str_chat_id = chat_id
        for u in data.get("users", []):
            if isinstance(u, dict) and u.get("chat_id") == str_chat_id:
                current = u.get("credits", data.get("default_credits", 3))
                u["credits"] = max(0, current - 1)
                break
        save_stats(data)


def check_global_cooldown():
    global last_global_run_time
    now = time.time()
    elapsed = now - last_global_run_time
    limit = get_cooldown_seconds()
    return (True, 0) if elapsed >= limit else (False, max(1, limit - int(elapsed)))


def update_global_run_time():
    global last_global_run_time
    last_global_run_time = time.time()


def get_cooldown_seconds():
    with stats_lock:
        return load_stats().get("cooldown_seconds", 60)


def set_cooldown_seconds(val):
    with stats_lock:
        data = load_stats()
        data["cooldown_seconds"] = int(val)
        save_stats(data)


def get_max_concurrent_tasks():
    with stats_lock:
        return load_stats().get("max_concurrent_tasks", 15)


def set_max_concurrent_tasks(val):
    with stats_lock:
        data = load_stats()
        data["max_concurrent_tasks"] = int(val)
        save_stats(data)


def is_user_registered(chat_id):
    with stats_lock:
        data = load_stats()
        try:
            str_chat_id = int(chat_id)
        except Exception:
            str_chat_id = chat_id
        for u in data.get("users", []):
            if isinstance(u, dict) and u.get("chat_id") == str_chat_id:
                return True
        return False


def find_cracked_record(mobile):
    with stats_lock:
        data = load_stats()
        clean = re.sub(r'\D', '', str(mobile))
        for rec in data.get("cracked_history", []):
            if re.sub(r'\D', '', str(rec.get("mobile", ""))) == clean:
                return rec
        return None


# ============================================================
# SECTION 7: UTILITIES
# ============================================================
def escape_html(s):
    return str(s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def get_ui_card(step_num, title, description, target=None, show_tip=True):
    body = ""
    if step_num:
        body += f"📱 <b>STEP {step_num}/4: {title}</b>\n\n"
    else:
        body += f"⭐ <b>{title}</b>\n\n"
    body += f"{description}\n"
    if target:
        body += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n📱 <b>Target Mobile:</b> <code>{target}</code>\n"
    if show_tip:
        body += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n💡 <i>Tip: Send <b>/cancel</b> to abort.</i>"
    else:
        body += "━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return body


def _build_session():
    s = requests.Session()
    retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def _build_headers(request_id=None):
    if request_id is None:
        request_id = str(uuid.uuid4())
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en_IN",
        "Content-Type": "application/json",
        "appid": "MYAADHAAR",
        "x-request-id": request_id,
        "Origin": "https://myaadhaar.uidai.gov.in",
        "Referer": "https://myaadhaar.uidai.gov.in/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Connection": "keep-alive"
    }, request_id


# ============================================================
# SECTION 8: GLOBAL REGISTRY
# ============================================================
user_page_registry = {}
buffered_inputs = {}
_running_loop = None
active_engines = {}
active_tasks = set()


async def init_pool(bot_instance):
    global _running_loop
    _running_loop = asyncio.get_running_loop()


# ============================================================
# SECTION 9: AADHAAR ENGINE
# ============================================================
class AadhaarEngine:
    def __init__(self, bot, chat_id=None):
        self.bot = bot
        self.chat_id = str(chat_id) if chat_id else None
        self.ocr = None
        if DDDDOCR_AVAILABLE:
            try:
                self.ocr = ddddocr.DdddOcr(show_ad=False)
            except Exception as e:
                print(f"⚠️ ddddocr init failed: {e}")
                self.ocr = None
        self.status_msg_id = None
        self._preloader_active = False
        self._preloader_task = None
        self.temp_msg_ids = []
        self.phase1_process = None
        self.phase1_task = None
        self.phase1_ready = None
        self.phase1_mobile = None
        self.start_time = None

    def update_status(self, text):
        if not self.chat_id or self.chat_id == "master":
            return
        footer = f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Dev: {DEVELOPER_USERNAME}</i>"
        if self.status_msg_id:
            try:
                self.bot.edit_message_text(chat_id=self.chat_id, message_id=self.status_msg_id,
                                           text=f"{text}{footer}", parse_mode='HTML')
            except Exception:
                pass
        else:
            try:
                msg = self.bot.send_message(self.chat_id, f"{text}{footer}", parse_mode='HTML')
                self.status_msg_id = msg.message_id
                try:
                    if int(self.chat_id) < 0:
                        self.temp_msg_ids.append(self.status_msg_id)
                except Exception:
                    pass
            except Exception:
                pass

    def refresh_status_card(self, text):
        if not self.chat_id or self.chat_id == "master":
            return
        if self.status_msg_id:
            try:
                self.bot.delete_message(chat_id=self.chat_id, message_id=self.status_msg_id)
            except Exception:
                pass
            self.status_msg_id = None
        self.update_status(text)

    def start_preloader(self, base_text):
        self.stop_preloader()
        self._preloader_active = True
        self.preloader_base_text = base_text
        target_loop = _running_loop
        if target_loop and target_loop.is_running():
            self._preloader_task = target_loop.create_task(self._preloader_loop())

    def stop_preloader(self):
        self._preloader_active = False
        if hasattr(self, '_preloader_task') and self._preloader_task:
            try:
                self._preloader_task.cancel()
            except Exception:
                pass
            self._preloader_task = None

    async def _preloader_loop(self):
        spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        bars = ["▒░░░░░░░░░", "█▒░░░░░░░░", "██▒░░░░░░░", "███▒░░░░░░", "████▒░░░░░",
                "█████▒░░░░", "██████▒░░░", "███████▒░░", "████████▒░", "█████████▒", "██████████"]
        idx = 0
        bar_idx = 0
        direction = 1
        while self._preloader_active:
            try:
                spin = spinner[idx % len(spinner)]
                bar = bars[bar_idx]
                bar_idx += direction
                if bar_idx >= len(bars) or bar_idx < 0:
                    direction *= -1
                    bar_idx += direction
                base_text = getattr(self, 'preloader_base_text', '⏳ Processing...')
                full_text = f"{base_text}\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n{spin} <b>{bar}</b>"
                footer = f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Dev: {DEVELOPER_USERNAME}</i>"
                if self.status_msg_id:
                    try:
                        self.bot.edit_message_text(chat_id=self.chat_id, message_id=self.status_msg_id,
                                                   text=f"{full_text}{footer}", parse_mode='HTML')
                    except Exception:
                        pass
                idx += 1
                await asyncio.sleep(1.2)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2)

    async def close(self):
        if self.chat_id == 'master':
            for uid, eng in list(active_engines.items()):
                try:
                    await eng.close()
                except Exception:
                    pass
            active_engines.clear()
            active_tasks.clear()
        try:
            if self.phase1_process:
                try:
                    self.phase1_process.terminate()
                except Exception:
                    pass
                self.phase1_process = None
            if self.phase1_task:
                try:
                    self.phase1_task.cancel()
                except Exception:
                    pass
                self.phase1_task = None
        except Exception as e:
            print(f"⚠️ ENGINE close: {e}")

    async def delete_temp_messages(self):
        if not self.chat_id:
            return
        try:
            chat_id_int = int(self.chat_id)
        except ValueError:
            return
        if chat_id_int < 0:
            for msg_id in list(self.temp_msg_ids):
                try:
                    self.bot.delete_message(chat_id=chat_id_int, message_id=msg_id)
                except Exception:
                    pass
            self.temp_msg_ids.clear()

    async def wait_for_input(self, chat_id, prompt_type, timeout=60):
        str_chat_id = str(chat_id)
        if str_chat_id in buffered_inputs:
            val = buffered_inputs.pop(str_chat_id)
            if val == '__CANCEL__':
                raise Exception("Process cancelled")
            return val
        user_page_registry[str_chat_id] = {'type': prompt_type, 'value': None}
        try:
            for _ in range(timeout):
                if str_chat_id in buffered_inputs:
                    val = buffered_inputs.pop(str_chat_id)
                    if val == '__CANCEL__':
                        raise Exception("Process cancelled")
                    return val
                if user_page_registry.get(str_chat_id) and user_page_registry[str_chat_id]['value'] is not None:
                    val = user_page_registry[str_chat_id]['value']
                    user_page_registry.pop(str_chat_id, None)
                    if val == '__CANCEL__':
                        raise Exception("Process cancelled")
                    return val
                await asyncio.sleep(1)
            raise Exception(f"Timeout waiting for {prompt_type}")
        finally:
            user_page_registry.pop(str_chat_id, None)

    async def _solve_captcha_manual(self, session, headers, chat_id, phase_label):
        captcha_payload = {"captchaLength": "6", "captchaType": "2", "audioCaptchaRequired": True}
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                res = session.post(CAPTCHA_URL, json=captcha_payload, headers=headers, timeout=15)
                res.raise_for_status()
                cap_data = res.json()
                if not cap_data or 'imageBase64' not in cap_data or 'transactionId' not in cap_data:
                    raise Exception("Invalid captcha response")
                img_b64 = cap_data['imageBase64']
                cap_txn_id = cap_data['transactionId']
                img_bytes = base64.b64decode(img_b64)

                captcha_val = None
                # Try OCR first
                if self.ocr is not None:
                    try:
                        ocr_res = self.ocr.classification(img_bytes)
                        candidate = re.sub(r'[^a-zA-Z0-9]', '', str(ocr_res or ''))
                        if len(candidate) == 6:
                            captcha_val = candidate
                            print(f"✅ OCR solved captcha: {captcha_val}")
                    except Exception as oe:
                        print(f"⚠️ OCR failed: {oe}")

                # Manual fallback
                if not captcha_val:
                    self.stop_preloader()
                    temp_path = os.path.join(BASE_DIR, f"temp_captcha_{phase_label}_{chat_id}.png")
                    with open(temp_path, 'wb') as f:
                        f.write(img_bytes)
                    with open(temp_path, 'rb') as f:
                        photo_msg = self.bot.send_photo(
                            chat_id, f,
                            caption=f"⚠️ <b>Captcha required (Attempt {attempt}/{max_attempts})</b>\n👇 Please type the 6-character captcha code:",
                            parse_mode='HTML'
                        )
                        try:
                            if photo_msg and int(chat_id) < 0:
                                self.temp_msg_ids.append(photo_msg.message_id)
                        except Exception:
                            pass
                    user_val = await self.wait_for_input(chat_id, 'CAPTCHA', timeout=120)
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                    if not user_val:
                        raise Exception("No captcha entered")
                    captcha_val = re.sub(r'[^a-zA-Z0-9]', '', user_val)

                if len(captcha_val) != 6:
                    self.bot.send_message(chat_id, "⚠️ Captcha must be exactly 6 characters. Please try again.")
                    continue
                return captcha_val, cap_txn_id
            except Exception as ex:
                if attempt == max_attempts:
                    raise Exception(f"Failed to solve captcha after {max_attempts} attempts: {ex}")
                print(f"⚠️ Captcha attempt {attempt} failed: {ex}")
                await asyncio.sleep(1)
        raise Exception("Captcha solving failed")

    async def run_flow(self, chat_id, name, mobile, dob, user_info=None):
        self.start_time = time.time()
        self.start_preloader(f"📱 <b>STEP 3/4: EID Retrieval</b>\n\n⏳ <b>Retrieving EID details...</b>\n📱 <b>Target Mobile:</b> <code>{mobile}</code>")
        try:
            found_id, captured_name = await self._run_eid_retrieval(chat_id, name, mobile, dob)
        except Exception as e:
            self.stop_preloader()
            raise e
        if found_id:
            self.stop_preloader()
            await self.run_uidai_phase(chat_id, found_id, captured_name, mobile, user_info=user_info)

    async def _run_eid_retrieval(self, chat_id, name, mobile, dob):
        if dob in ("None", "null", ""):
            dob = None
        session = _build_session()
        headers, _ = _build_headers()
        name_clean = name.strip()
        if name_clean.lower() == "mr":
            candidates = ["Mr", "Mr.", "Shri", "Sh.", "Kumar"]
        elif name_clean.lower() == "mrs":
            candidates = ["Mrs", "Mrs.", "Ms", "Ms.", "Smt", "Smt.", "Miss", "Kumari"]
        else:
            candidates = [name_clean]
        otp_txn_id = None
        last_server_msg = "Failed to send OTP."
        success_details_payload = None
        success_captcha_val = None
        technical_diff = False

        for full_name in candidates:
            if technical_diff:
                break
            print(f"🔍 Trying '{full_name}'...")
            self.preloader_base_text = f"📱 <b>STEP 3/4: EID Retrieval</b>\n\n🔍 <b>Searching...</b>\n\n📱 <b>Target Mobile:</b> <code>{mobile}</code>"
            for attempt in range(1, 3):
                try:
                    captcha_val, cap_txn_id = await self._solve_captcha_manual(session, headers, chat_id, "p1")
                    payload = {
                        "name": full_name, "mobileNumber": str(mobile), "dob": dob,
                        "email": None, "captcha": captcha_val, "captchaTxnId": cap_txn_id,
                        "option": "EID", "otp": None, "otpTxnId": None, "resendOtp": False
                    }
                    res = session.post(RETRIEVE_URL, json=payload, headers=headers, timeout=20)
                    try:
                        data = res.json()
                    except ValueError:
                        raise Exception("Invalid JSON from UIDAI")
                    res_data = data.get('responseData') or {}
                    if data.get('status') == "Success" or res_data.get('otpSent'):
                        otp_txn_id = res_data.get('otpTxnId')
                        if otp_txn_id:
                            print(f"✅ OTP sent for {full_name}")
                            success_details_payload = payload
                            success_captcha_val = captcha_val
                            break
                    msg = res_data.get('message') or data.get('message') or ''
                    if msg:
                        last_server_msg = msg
                    if "technical difficulties" in msg.lower():
                        technical_diff = True
                        last_server_msg = f"⚠️ Technical difficulties. ||| {msg}"
                        break
                    if any(x in msg.lower() for x in ["mismatch", "no record", "validation failed", "invalid"]):
                        break
                except Exception as ex:
                    print(f"⚠️ Error for {full_name}: {ex}")
                    if attempt == 2:
                        raise
            if technical_diff:
                break
            if otp_txn_id:
                break

        if not otp_txn_id:
            raise Exception(last_server_msg)
        self.stop_preloader()
        otp_card = get_ui_card(3, "OTP 1 Verification",
                               "🚀 <b>OTP 1 Sent Successfully!</b>\n👇 Please type the OTP:",
                               target=mobile)
        self.update_status(otp_card)
        otp_code = await self.wait_for_input(chat_id, 'OTP', timeout=120)
        self.refresh_status_card(f"📱 <b>STEP 3/4: OTP 1 Verification</b>\n\n⏳ <b>Submitting OTP...</b>")
        self.start_preloader(f"📱 <b>STEP 3/4: OTP 1 Verification</b>\n\n⏳ <b>Submitting...</b>")
        if not otp_code:
            raise Exception("No OTP entered")
        final_payload = success_details_payload.copy()
        final_payload["otp"] = otp_code
        final_payload["otpTxnId"] = otp_txn_id
        final_payload["captcha"] = success_captcha_val
        res_final = session.post(RETRIEVE_URL, json=final_payload, headers=headers, timeout=20)
        final_data = res_final.json()
        found_id = None
        captured_name = name
        if final_data.get('status') == "Success":
            res_data = final_data.get('responseData') or {}
            found_id = res_data.get('eidNumber') or res_data.get('uidNumber') or res_data.get('aadhaarNumber')
            captured_name = res_data.get('name') or name
            if found_id:
                found_id = re.sub(r'[^a-zA-Z0-9]', '', found_id)
        else:
            err = final_data.get('responseData', {}).get('message', 'Incorrect OTP')
            raise Exception(f"OTP submission failed: {err}")
        return found_id, captured_name

    async def run_uidai_phase(self, chat_id, eid, name, mobile, user_info=None):
        self.start_preloader(f"📱 <b>STEP 4/4: Aadhaar Download</b>\n\n⏳ <b>Fetching PDF...</b>\n📱 <b>Target Mobile:</b> <code>{mobile}</code>")
        for retry in range(2):
            try:
                await self._run_aadhaar_download(chat_id, eid, mobile)
                file_path = os.path.join(CRACKED_DIR, f"Aadhaar_{chat_id}.pdf")
                if os.path.exists(file_path):
                    await self.process_cracked_pdf(chat_id, file_path, name, mobile, eid=eid, user_info=user_info)
                    return
                else:
                    raise Exception("Download failed")
            except Exception as e:
                self.stop_preloader()
                err = str(e)
                if "technical difficulties" in err.lower():
                    raise e
                is_otp_error = "invalid otp" in err.lower() or "incorrect otp" in err.lower()
                if retry < 1:
                    if is_otp_error:
                        self.update_status("❌ OTP wrong / session expired. Retrying...")
                    else:
                        self.update_status(f"⚠️ Error: {escape_html(err)}\nRetrying...")
                    await asyncio.sleep(2)
                else:
                    raise Exception("❌ Invalid OTP" if is_otp_error else f"Registry Phase Failed: {err}")

    async def _run_aadhaar_download(self, chat_id, eid, mobile):
        session = _build_session()
        headers, request_id = _build_headers()
        otp_txn_id = None
        for attempt in range(1, 4):
            try:
                captcha_val, cap_txn_id = await self._solve_captcha_manual(session, headers, chat_id, "p2")
                otp_payload = {
                    "eidNumber": eid, "idType": "eid",
                    "captchaTxnId": cap_txn_id, "captchaValue": captcha_val,
                    "resendOTP": False, "transactionId": request_id
                }
                res = session.post(OTP_URL, json=otp_payload, headers=headers, timeout=20)
                try:
                    otp_data = res.json()
                except ValueError:
                    raise Exception("Invalid JSON from OTP request")
                if otp_data.get('status') == "Success":
                    otp_txn_id = otp_data['txnId']
                    break
                else:
                    msg = otp_data.get('message') or (otp_data.get('responseData') or {}).get('message') or 'OTP failed'
                    if "technical difficulties" in msg.lower():
                        raise Exception(f"Technical difficulties. ||| {msg}")
                    print(f"OTP attempt {attempt}: {msg}")
            except Exception as ex:
                if attempt == 3:
                    raise Exception(f"Failed after 3 attempts: {ex}")
                await asyncio.sleep(1)
        if not otp_txn_id:
            raise Exception("Could not get OTP")
        self.stop_preloader()
        otp2_card = get_ui_card(4, "OTP 2 Verification",
                                "✅ <b>OTP 2 Sent!</b>\n👇 Please type the OTP:",
                                target=mobile)
        self.update_status(otp2_card)
        otp_code = await self.wait_for_input(chat_id, 'OTP', timeout=120)
        self.refresh_status_card(f"📱 <b>STEP 4/4: OTP 2 Verification</b>\n\n⏳ <b>Submitting OTP...</b>")
        self.start_preloader(f"📱 <b>STEP 4/4: OTP 2 Verification</b>\n\n⏳ <b>Submitting...</b>")
        if not otp_code:
            raise Exception("No OTP")
        download_payload = {"eid": eid, "mask": False, "otp": otp_code, "otpTxnId": otp_txn_id}
        dl_headers = headers.copy()
        dl_headers["transactionId"] = request_id
        res_dl = session.post(DOWNLOAD_URL, json=download_payload, headers=dl_headers, timeout=30)
        dl_data = res_dl.json()
        if dl_data.get('status') == "Success":
            pdf_b64 = dl_data['data']['aadhaarPdf']
            pdf_bytes = base64.b64decode(pdf_b64)
            os.makedirs(CRACKED_DIR, exist_ok=True)
            file_path = os.path.join(CRACKED_DIR, f"Aadhaar_{chat_id}.pdf")
            with open(file_path, 'wb') as f:
                f.write(pdf_bytes)
            print(f"✅ PDF saved: {file_path}")
        else:
            err = dl_data.get('statusMessage', 'Download failed')
            raise Exception(f"Download failed: {err}")

    async def process_cracked_pdf(self, chat_id, file_path, name, mobile, eid=None, user_info=None):
        self.start_preloader("🔓 Unlocking PDF...")
        try:
            proc_script = os.path.join(BASE_DIR, 'pdf_processor.py')
            if not os.path.exists(proc_script):
                raise Exception("pdf_processor.py not found")
            process = await asyncio.create_subprocess_exec(
                sys.executable, proc_script, file_path, name, CRACKED_DIR, str(chat_id),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            stdout_str = stdout.decode('utf-8', errors='ignore')
            stderr_str = stderr.decode('utf-8', errors='ignore').strip()
            if stdout_str.strip():
                print(f"[pdf_processor] {stdout_str.strip()}")
            if stderr_str:
                print(f"[pdf_processor stderr] {stderr_str}")

            success_line = uncracked_line = error_line = None
            for line in stdout_str.split('\n'):
                line = line.strip()
                if line.startswith('SUCCESS|'):
                    success_line = line
                    break
                if line.startswith('UNCRACKED|'):
                    uncracked_line = line
                    break
                if line.startswith('ERROR|'):
                    error_line = line[6:]
                    break

            if success_line:
                self.stop_preloader()
                parts = success_line.split('|', 5)
                if len(parts) < 6:
                    raise Exception("Malformed SUCCESS line")
                _, uid, pdf_out, front, back, password = parts
                time_str = "<b>N/A</b>"
                if self.start_time:
                    sec = int(time.time() - self.start_time)
                    m, s = sec // 60, sec % 60
                    time_str = f"<b>{m} min {s} sec</b>" if m > 0 else f"<b>{s} sec</b>"
                success_text = (
                    f"🎉 <b>Success! Aadhaar Cracked.</b>\n\n"
                    f"👤 <b>Name:</b> <code>{name}</code>\n"
                    f"🆔 <b>EID:</b> <code>{eid or 'N/A'}</code>\n"
                    f"🔢 <b>Aadhaar:</b> <code>{uid}</code>\n"
                    f"🔑 <b>Password:</b> <code>{password}</code>\n\n"
                    f"⏱️ <b>Time Taken:</b> {time_str}"
                )
                try:
                    self.bot.send_message(chat_id, success_text, parse_mode='HTML')
                except Exception:
                    pass
                try:
                    record_success(chat_id, user_info, name, mobile, uid, password, eid=eid)
                except Exception as se:
                    print(f"⚠️ record success: {se}")
                try:
                    safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
                    safe_uid = uid.replace(' ', '')
                    perm_path = os.path.join(CRACKED_DIR, f"{safe_name}_{safe_uid}.pdf")
                    shutil.copy(pdf_out, perm_path)
                except Exception as e_copy:
                    print(f"⚠️ copy perm: {e_copy}")
                self.update_status("📤 Sending files...")
                try:
                    if os.path.exists(front):
                        with open(front, 'rb') as f:
                            self.bot.send_photo(chat_id, f, caption="🖼️ <b>Front</b>", parse_mode='HTML')
                except Exception as e_front:
                    print(f"⚠️ front: {e_front}")
                try:
                    if os.path.exists(back):
                        with open(back, 'rb') as f:
                            self.bot.send_photo(chat_id, f, caption="🖼️ <b>Back</b>", parse_mode='HTML')
                except Exception as e_back:
                    print(f"⚠️ back: {e_back}")
                try:
                    if os.path.exists(pdf_out):
                        with open(pdf_out, 'rb') as f:
                            self.bot.send_document(chat_id, f, caption="📄 <b>PDF (Unlocked)</b>")
                except Exception as e_pdf:
                    print(f"⚠️ pdf: {e_pdf}")
                self.update_status("✅ Process completed.")
                for f in [front, back, pdf_out, file_path]:
                    if f and os.path.exists(f):
                        try:
                            os.remove(f)
                        except Exception:
                            pass
                return

            if uncracked_line:
                self.stop_preloader()
                parts = uncracked_line.split('|', 1)
                locked_pdf_path = parts[1] if len(parts) > 1 else file_path
                time_str = "<b>N/A</b>"
                if self.start_time:
                    sec = int(time.time() - self.start_time)
                    m, s = sec // 60, sec % 60
                    time_str = f"<b>{m} min {s} sec</b>" if m > 0 else f"<b>{s} sec</b>"
                uncracked_text = (
                    f"⚠️ <b>Aadhaar Crack Failed!</b>\n\n"
                    f"👤 <b>Name:</b> <code>{name}</code>\n"
                    f"🆔 <b>EID:</b> <code>{eid or 'N/A'}</code>\n"
                    f"🔑 <b>Password:</b> Not found\n\n"
                    f"ℹ️ Sending locked PDF. Manual password: First 4 letters of name + birth year.\n"
                    f"⏱️ {time_str}"
                )
                try:
                    self.bot.send_message(chat_id, uncracked_text, parse_mode='HTML')
                except Exception:
                    pass
                try:
                    record_failure()
                except Exception:
                    pass
                self.update_status("📤 Sending locked PDF...")
                try:
                    if os.path.exists(locked_pdf_path):
                        with open(locked_pdf_path, 'rb') as f:
                            self.bot.send_document(chat_id, f, caption="📄 <b>PDF (Locked)</b>")
                except Exception as e_pdf:
                    print(f"⚠️ locked pdf: {e_pdf}")
                self.update_status("✅ Process completed.")
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                return

            if error_line:
                raise Exception(f"PDF Error: {error_line}")
            elif stderr_str:
                last_err = [l for l in stderr_str.splitlines() if l.strip()][-1] if stderr_str else "Unknown"
                raise Exception(f"PDF Processor crashed: {last_err}")
            else:
                raise Exception("PDF Cracking failed – password not found or PDF unreadable.")
        except Exception as e:
            self.stop_preloader()
            self.update_status(f"❌ PDF Crack Error: {escape_html(str(e))}")


# ============================================================
# SECTION 10: ENGINE ENTRY POINTS
# ============================================================
async def execute_task(bot, chat_id, name, mobile, dob, user_info=None):
    str_chat_id = str(chat_id)
    if str_chat_id in active_tasks:
        bot.send_message(chat_id, "⏳ Already processing. Please wait.", parse_mode='HTML')
        return False
    if len(active_tasks) >= get_max_concurrent_tasks():
        bot.send_message(chat_id, f"⚠️ Bot overloaded. Max {get_max_concurrent_tasks()} concurrent. Try later.", parse_mode='HTML')
        return False
    active_tasks.add(str_chat_id)
    if str_chat_id in active_engines:
        engine = active_engines[str_chat_id]
    else:
        engine = AadhaarEngine(bot, chat_id=str_chat_id)
        active_engines[str_chat_id] = engine
    try:
        await engine.run_flow(chat_id, name, mobile, dob, user_info=user_info)
    except Exception as e:
        err = str(e)
        if "|||" in err:
            user_msg, real_msg = err.split("|||", 1)
            user_msg = user_msg.strip()
            real_msg = real_msg.strip()
        else:
            user_msg = err
            real_msg = err
        engine.update_status(f"❌ Task Failed: {escape_html(user_msg)}")
        try:
            is_user_error = any(x in user_msg.lower() for x in [
                "no record", "not found", "mismatch", "validation failed",
                "invalid captcha", "incorrect otp", "invalid otp",
                "incorrect details", "wrong captcha", "galat hain",
                "match nahi", "incorrect", "invalid"
            ])
            if not is_user_error:
                record_failure()
            log_error(chat_id, user_info, f"Task Failed: {real_msg}")
        except Exception as se:
            print(f"⚠️ failure log: {se}")
    finally:
        if str_chat_id in active_engines:
            del active_engines[str_chat_id]
        if str_chat_id in active_tasks:
            active_tasks.remove(str_chat_id)
        try:
            await engine.delete_temp_messages()
        except Exception:
            pass
        await engine.close()
    return True


def prewarm_engine(bot, chat_id, mobile=None):
    str_chat_id = str(chat_id)
    if str_chat_id in active_engines:
        return
    engine = AadhaarEngine(bot, chat_id=str_chat_id)
    active_engines[str_chat_id] = engine


# ============================================================
# SECTION 11: TELEGRAM BOT SETUP
# ============================================================
class BotExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        print(f"⚠️ TELEBOT EXCEPTION: {exception}")
        if any(x in str(exception) for x in ["getaddrinfo failed", "NewConnectionError", "Max retries exceeded"]):
            time.sleep(5)
        return True


apihelper.SESSION_TIME_TO_LIVE = 5 * 60
bot = telebot.TeleBot(TOKEN, parse_mode='HTML', exception_handler=BotExceptionHandler())

try:
    bot.remove_webhook()
    print("✅ Webhook removed")
except Exception as e:
    print(f"⚠️ Failed to remove webhook: {e}")

# Safe wrappers
orig_send = bot.send_message
orig_edit = bot.edit_message_text
orig_photo = bot.send_photo
orig_doc = bot.send_document


def safe_send(*a, **k):
    k.pop('timeout', None)
    for attempt in range(3):
        try:
            return orig_send(*a, **k)
        except Exception as e:
            if any(x in str(e) for x in ["blocked", "Forbidden", "chat not found", "403"]):
                raise e
            if attempt == 2:
                raise e
            time.sleep(1)


def safe_edit(*a, **k):
    k.pop('timeout', None)
    for attempt in range(3):
        try:
            return orig_edit(*a, **k)
        except Exception as e:
            if "message is not modified" in str(e):
                return True
            if any(x in str(e) for x in ["blocked", "Forbidden", "chat not found", "403"]):
                raise e
            if attempt == 2:
                raise e
            time.sleep(1)


def safe_photo(*a, **k):
    k.pop('timeout', None)
    for attempt in range(3):
        try:
            return orig_photo(*a, **k)
        except Exception as e:
            if attempt == 2:
                raise e
            time.sleep(2)


def safe_doc(*a, **k):
    k.pop('timeout', None)
    for attempt in range(3):
        try:
            return orig_doc(*a, **k)
        except Exception as e:
            if attempt == 2:
                raise e
            time.sleep(2)


bot.send_message = safe_send
bot.edit_message_text = safe_edit
bot.send_photo = safe_photo
bot.send_document = safe_doc

user_states = {}
# ✅ FIX: loop module-level এ রাখা হয়েছে
loop = None


def check_user_joined(chat_id):
    if chat_id < 0 or chat_id in ADMIN_IDS or not REQUIRED_CHANNELS:
        return True
    for ch in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(chat_id=ch, user_id=chat_id)
            if member.status in ['left', 'kicked']:
                return False
        except apihelper.ApiTelegramException as e:
            if "user not found" in str(e).lower():
                return False
        except Exception as e:
            print(f"⚠️ join check: {e}")
    return True


def prompt_join_channels(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    text = "⚠️ <b>Join Required Channels</b>\n\nPlease join these channels to use the bot:\n"
    for idx, ch in enumerate(REQUIRED_CHANNELS, 1):
        url = None
        title = f"Channel {idx}"
        try:
            info = bot.get_chat(ch)
            title = info.title or f"Channel {idx}"
            if info.username:
                url = f"https://t.me/{info.username}"
            elif info.invite_link:
                url = info.invite_link
            else:
                try:
                    url = bot.export_chat_invite_link(ch)
                except Exception:
                    url = f"https://t.me/c/{str(ch).replace('-100', '')}"
        except Exception:
            url = "https://t.me/"
        markup.add(types.InlineKeyboardButton(f"📢 Join {title}", url=url))
    markup.add(types.InlineKeyboardButton("🔄 Re-Verify / Start", callback_data="check_joined_status"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


def send_zero_credits_dashboard(chat_id, message_id=None):
    data = load_stats()
    try:
        str_chat_id = int(chat_id)
    except Exception:
        str_chat_id = chat_id
    user_record = None
    for u in data.get("users", []):
        if isinstance(u, dict) and str(u.get("chat_id")) == str(chat_id):
            user_record = u
            break
    join_date = user_record.get("joined", "N/A") if user_record else "N/A"
    history = data.get("cracked_history", [])
    success_count = sum(1 for r in history if str(r.get("chat_id")) == str(chat_id))
    text = (
        f"🚫 <b>NO CREDITS REMAINING!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Your credits are exhausted. Contact admin to get more.\n\n"
        f"👤 <b>PROFILE:</b>\n  ├─ ID: <code>{chat_id}</code>\n"
        f"  ├─ Joined: <code>{join_date}</code>\n  ├─ Credits: <code>0 💳</code>\n"
        f"  └─ Success: <code>{success_count} ✅</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👨‍💻 Contact Admin", url=f"https://t.me/{DEVELOPER_USERNAME.lstrip('@')}"),
        types.InlineKeyboardButton("🔄 Refresh", callback_data="refresh_zero_credits")
    )
    if message_id:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text,
                                  reply_markup=markup, parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


def send_welcome_dashboard(chat_id, message_id=None):
    mode = get_bot_mode()
    credits = get_user_credits(chat_id)
    if mode == "paid":
        credits_info = f"\n💳 <b>Credits Left:</b> <code>{credits} 💳</code>\n" if credits > 0 else "\n🚫 <b>Credits:</b> <code>0 💳 (Contact Admin)</code>\n"
    else:
        credits_info = "\n💳 <b>Credits Left:</b> <code>Unlimited</code>\n"
    text = (
        f"👋 <b>Welcome to Aadhaar BOT!</b>\n"
        f"Extract Aadhaar details and PDFs instantly.\n"
        f"{credits_info}\n⚡ <b>Select an option:</b>"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👨‍💻 Developer", url=f"https://t.me/{DEVELOPER_USERNAME.lstrip('@')}"),
        types.InlineKeyboardButton("🚀 Start", callback_data="start_bypass"),
        types.InlineKeyboardButton("💳 My Credits", callback_data="check_my_credits")
    )
    if message_id:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text,
                                  reply_markup=markup, parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


# ============================================================
# SECTION 12: HANDLERS
# ============================================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    is_new = not is_user_registered(chat_id)
    try:
        register_visit(chat_id, username=message.from_user.username, first_name=message.from_user.first_name)
    except Exception:
        pass
    if is_new:
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id,
                                 f"🔔 <b>New User</b>\nName: {message.from_user.first_name}\n"
                                 f"Username: @{message.from_user.username or 'N/A'}\n"
                                 f"ID: <code>{chat_id}</code>",
                                 parse_mode='HTML')
            except Exception:
                pass
    if not check_user_joined(chat_id):
        prompt_join_channels(chat_id)
        return
    str_chat_id = str(chat_id)
    if str_chat_id in active_tasks or user_states.get(chat_id, {}).get('step') in ['PROCESSING', 'FETCHING_INFO']:
        bot.send_message(chat_id, "⚠️ Active session running. Please wait or /cancel.", parse_mode='HTML')
        return
    user_states[chat_id] = {'step': 'IDLE'}
    send_welcome_dashboard(chat_id)


@bot.callback_query_handler(func=lambda call: call.data == 'start_bypass')
def handle_start_bypass(call):
    chat_id = call.message.chat.id
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    if not check_user_joined(chat_id):
        try:
            bot.delete_message(chat_id=chat_id, message_id=call.message.message_id)
        except Exception:
            pass
        prompt_join_channels(chat_id)
        return
    if get_bot_mode() == "paid" and get_user_credits(chat_id) <= 0:
        send_zero_credits_dashboard(chat_id, message_id=call.message.message_id)
        return
    user_states[chat_id] = {'step': 'AWAITING_MOBILE'}
    txt = get_ui_card(1, "Mobile Verification", "Please send the <b>10-digit Mobile Number</b> linked to Aadhaar.")
    try:
        bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=txt, parse_mode='HTML')
    except Exception:
        bot.send_message(chat_id, txt, parse_mode='HTML')


def get_admin_dashboard_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    mode = get_bot_mode()
    markup.add(
        types.InlineKeyboardButton("🔓 Mode: FREE" if mode == "free" else "🔒 Mode: PAID", callback_data="admin_toggle_mode"),
        types.InlineKeyboardButton("💳 Default Credits", callback_data="admin_set_default_credits"),
        types.InlineKeyboardButton("⚙️ System Settings", callback_data="admin_settings_menu"),
        types.InlineKeyboardButton("👁 Recent Cracks", callback_data="admin_view_recent_cracks"),
        types.InlineKeyboardButton("➕ Grant Credits", callback_data="admin_grant_credits"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("👥 View Users", callback_data="admin_view_users_page_1"),
        types.InlineKeyboardButton("📤 Export Users", callback_data="admin_download_users"),
        types.InlineKeyboardButton("👁 Error Logs", callback_data="admin_view_logs"),
        types.InlineKeyboardButton("📤 Export Logs", callback_data="admin_download_logs"),
        types.InlineKeyboardButton("📂 Cracked Database", callback_data="admin_download_cracked"),
        types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")
    )
    return markup


def send_admin_dashboard(chat_id):
    summary = get_stats_summary(user_states)
    bot.send_message(chat_id, summary, reply_markup=get_admin_dashboard_markup(), parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_callbacks(call):
    chat_id = call.message.chat.id
    if chat_id not in ADMIN_IDS:
        try:
            bot.answer_callback_query(call.id, "Access Denied!")
        except Exception:
            pass
        return
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    action = call.data
    if action == "admin_stats":
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id,
                                  text=get_stats_summary(user_states),
                                  reply_markup=get_admin_dashboard_markup(), parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, get_stats_summary(user_states),
                             reply_markup=get_admin_dashboard_markup(), parse_mode='HTML')
    elif action == "admin_settings_menu":
        cooldown = get_cooldown_seconds()
        maxc = get_max_concurrent_tasks()
        txt = f"⚙️ <b>SYSTEM SETTINGS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n⏳ Cooldown: <b>{cooldown}s</b>\n⚡ Max Concurrent: <b>{maxc}</b>"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"⏳ Cooldown ({cooldown}s)", callback_data="admin_set_cooldown"),
            types.InlineKeyboardButton(f"⚡ Max Concurrent ({maxc})", callback_data="admin_set_concurrent"),
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_stats")
        )
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=txt,
                                  reply_markup=markup, parse_mode='HTML')
        except Exception:
            pass
    elif action == "admin_set_cooldown":
        user_states[chat_id] = {'step': 'AWAITING_ADMIN_COOLDOWN'}
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Cancel")
        bot.send_message(chat_id, "⏳ Enter cooldown seconds:", reply_markup=markup, parse_mode='HTML')
    elif action == "admin_set_concurrent":
        user_states[chat_id] = {'step': 'AWAITING_ADMIN_MAX_CONCURRENT'}
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Cancel")
        bot.send_message(chat_id, "⚡ Enter max concurrent tasks:", reply_markup=markup, parse_mode='HTML')
    elif action == "admin_view_recent_cracks":
        data = load_stats()
        history = data.get("cracked_history", [])[-5:]
        txt = "👁 <b>RECENT CRACKS (Last 5)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        if not history:
            txt += "<i>No records</i>"
        else:
            for idx, rec in enumerate(reversed(history), 1):
                txt += (f"🎯 <b>{idx}. {rec.get('name', 'N/A')}</b>\n"
                        f"  ├─ Time: <code>{rec.get('timestamp', 'N/A')}</code>\n"
                        f"  ├─ User: {rec.get('first_name', 'N/A')} (@{rec.get('username', 'N/A')})\n"
                        f"  ├─ Mobile: <code>{rec.get('mobile', 'N/A')}</code>\n"
                        f"  ├─ Aadhaar: <code>{rec.get('uid', 'N/A')}</code>\n"
                        f"  └─ Pass: <code>{rec.get('password', 'N/A')}</code>\n────────────────────\n")
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_view_recent_cracks"),
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_stats")
        )
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=txt,
                                  reply_markup=markup, parse_mode='HTML')
        except Exception:
            pass
    elif action == "admin_toggle_mode":
        cur = get_bot_mode()
        new = "paid" if cur == "free" else "free"
        set_bot_mode(new)
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id,
                                  text=get_stats_summary(user_states),
                                  reply_markup=get_admin_dashboard_markup(), parse_mode='HTML')
        except Exception:
            pass
    elif action == "admin_set_default_credits":
        user_states[chat_id] = {'step': 'AWAITING_ADMIN_DEFAULT_CREDITS'}
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Cancel")
        bot.send_message(chat_id, "💳 Enter default credits for new users:", reply_markup=markup, parse_mode='HTML')
    elif action == "admin_grant_credits":
        user_states[chat_id] = {'step': 'AWAITING_ADMIN_GRANT_USER_ID'}
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Cancel")
        bot.send_message(chat_id, "➕ Enter User ID (Chat ID):", reply_markup=markup, parse_mode='HTML')
    elif action == "admin_broadcast":
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Cancel")
        bot.send_message(chat_id, "📢 Send the message to broadcast (text/photo/doc):", reply_markup=markup, parse_mode='HTML')
    elif action == "admin_download_cracked":
        bot.send_message(chat_id, "⏳ Generating report...", parse_mode='HTML')
        perm = os.path.join(BASE_DIR, "cracked_history.txt")
        if os.path.exists(perm) and os.path.getsize(perm) > 0:
            try:
                tmp = os.path.join(BASE_DIR, "cracked_history_temp.txt")
                shutil.copy(perm, tmp)
                report_path = tmp
            except Exception:
                report_path = get_cracked_data_file_path()
        else:
            report_path = get_cracked_data_file_path()
        if report_path and os.path.exists(report_path):
            with open(report_path, 'rb') as f:
                bot.send_document(chat_id, f, caption="📂 Cracked Database")
            try:
                os.remove(report_path)
            except Exception:
                pass
        else:
            bot.send_message(chat_id, "❌ No data.", parse_mode='HTML')
    elif action == "admin_download_users":
        data = load_stats()
        users = data.get("users", [])
        if not users:
            bot.send_message(chat_id, "❌ No users.", parse_mode='HTML')
            return
        file_path = os.path.join(BASE_DIR, "users_list.txt")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"USERS ({len(users)})\n")
            for idx, u in enumerate(users, 1):
                if isinstance(u, dict):
                    f.write(f"{idx}. {u.get('first_name', 'N/A')} (@{u.get('username', 'N/A')}) ID:{u.get('chat_id', 'N/A')} Credits:{u.get('credits', 0)}\n")
                else:
                    f.write(f"{idx}. {u}\n")
        with open(file_path, 'rb') as f:
            bot.send_document(chat_id, f, caption="👥 Users List")
        try:
            os.remove(file_path)
        except Exception:
            pass
    elif action == "admin_download_logs":
        log_path = get_error_log_file_path()
        if log_path and os.path.exists(log_path):
            with open(log_path, 'rb') as f:
                bot.send_document(chat_id, f, caption="⚠️ Error Logs")
        else:
            bot.send_message(chat_id, "✅ No errors logged.", parse_mode='HTML')
    elif action.startswith("admin_view_users_page_"):
        page = int(action.split("_")[-1]) if action.split("_")[-1].isdigit() else 1
        data = load_stats()
        users = data.get("users", [])
        if not users:
            try:
                bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id,
                                      text="❌ No users.",
                                      reply_markup=get_admin_dashboard_markup(), parse_mode='HTML')
            except Exception:
                pass
            return
        PAGE = 5
        total = len(users)
        pages = max(1, (total + PAGE - 1) // PAGE)
        page = max(1, min(page, pages))
        start = (page - 1) * PAGE
        end = start + PAGE
        txt = f"👥 USERS (Page {page}/{pages})\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for idx, u in enumerate(users[start:end], start + 1):
            if isinstance(u, dict):
                txt += f"{idx}. {u.get('first_name', 'N/A')} (@{u.get('username', 'N/A')}) Credits:{u.get('credits', 0)}\n"
            else:
                txt += f"{idx}. {u}\n"
        markup = types.InlineKeyboardMarkup(row_width=2)
        if page > 1:
            markup.add(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_view_users_page_{page-1}"))
        if page < pages:
            markup.add(types.InlineKeyboardButton("➡️ Next", callback_data=f"admin_view_users_page_{page+1}"))
        markup.add(
            types.InlineKeyboardButton("📤 Export", callback_data="admin_download_users"),
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_stats")
        )
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=txt,
                                  reply_markup=markup, parse_mode='HTML')
        except Exception:
            pass
    elif action == "admin_view_logs":
        log_path = get_error_log_file_path()
        if not log_path:
            txt = "✅ No errors logged."
        else:
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            last = lines[-10:] if lines else []
            txt = "⚠️ <b>LAST 10 ERRORS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for line in last:
                txt += f"▪️ {line.strip()}\n"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_view_logs"),
            types.InlineKeyboardButton("📤 Export", callback_data="admin_download_logs"),
            types.InlineKeyboardButton("🔙 Back", callback_data="admin_stats")
        )
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=txt,
                                  reply_markup=markup, parse_mode='HTML')
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith('mp|'))
def handle_manual_pref_selection(call):
    chat_id = call.message.chat.id
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    parts = call.data.split('|')
    action = parts[1]
    state = user_states.get(chat_id, {})
    number = state.get('num', '')
    if action == 'manual':
        user_states[chat_id] = {'step': 'AWAITING_NAME', 'num': number, 'prefix': ''}
        txt = get_ui_card(2, "Aadhaar Holder Name", "Send the exact name as on card:", target=number)
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=txt, parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, txt, parse_mode='HTML')
    else:
        name = "Mr" if action == "Mr." else "Mrs"
        user_states[chat_id] = {'step': 'PROCESSING'}
        user_info = {
            'username': call.from_user.username or 'N/A',
            'first_name': call.from_user.first_name or 'N/A'
        }
        global loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                execute_and_reset(chat_id, name, number, None, user_info=user_info), loop
            )
        else:
            print("⚠️ loop not ready")


@bot.callback_query_handler(func=lambda call: call.data == 'refresh_zero_credits')
def handle_refresh_zero_credits(call):
    chat_id = call.message.chat.id
    try:
        bot.answer_callback_query(call.id, "Checking...", show_alert=False)
    except Exception:
        pass
    if chat_id in ADMIN_IDS or get_bot_mode() == "free":
        send_welcome_dashboard(chat_id, message_id=call.message.message_id)
        return
    credits = get_user_credits(chat_id)
    if credits > 0:
        try:
            bot.send_message(chat_id, f"🎉 Credits updated! You have {credits} credits.", parse_mode='HTML')
        except Exception:
            pass
        send_welcome_dashboard(chat_id, message_id=call.message.message_id)
    else:
        send_zero_credits_dashboard(chat_id, message_id=call.message.message_id)


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    if call.data == "check_my_credits":
        credits = get_user_credits(chat_id)
        mode = get_bot_mode()
        txt = (f"💳 <b>BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
               f"Balance: <b>{'Unlimited' if mode == 'free' else credits} 💳</b>\nMode: <code>{mode.upper()}</code>")
        if credits <= 0 and mode == "paid":
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("👨‍💻 Contact Admin",
                                                  url=f"https://t.me/{DEVELOPER_USERNAME.lstrip('@')}"))
            try:
                bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=txt,
                                      reply_markup=markup, parse_mode='HTML')
            except Exception:
                bot.send_message(chat_id, txt, reply_markup=markup, parse_mode='HTML')
        else:
            try:
                bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=txt, parse_mode='HTML')
            except Exception:
                bot.send_message(chat_id, txt, parse_mode='HTML')
    elif call.data == "check_joined_status":
        if check_user_joined(chat_id):
            try:
                bot.delete_message(chat_id=chat_id, message_id=call.message.message_id)
            except Exception:
                pass
            send_welcome_dashboard(chat_id)
        else:
            try:
                bot.answer_callback_query(call.id, "You haven't joined all channels!", show_alert=True)
            except Exception:
                pass


@bot.message_handler(commands=['profile'])
def handle_profile(message):
    chat_id = message.chat.id
    if not check_user_joined(chat_id):
        prompt_join_channels(chat_id)
        return
    data = load_stats()
    user_record = None
    for u in data.get("users", []):
        if isinstance(u, dict) and u.get("chat_id") == chat_id:
            user_record = u
            break
    if not user_record:
        register_visit(chat_id, username=message.from_user.username, first_name=message.from_user.first_name)
        data = load_stats()
    join_date = user_record.get("joined", "N/A") if user_record else "N/A"
    credits = get_user_credits(chat_id)
    mode = get_bot_mode()
    success_count = sum(1 for r in data.get("cracked_history", []) if r.get("chat_id") == chat_id)
    txt = (f"👤 <b>PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
           f"Name: {message.from_user.first_name}\nUsername: @{message.from_user.username or 'N/A'}\n"
           f"ID: <code>{chat_id}</code>\nJoined: <code>{join_date}</code>\n"
           f"Credits: <b>{'Unlimited' if mode == 'free' else credits} 💳</b>\nSuccess: <code>{success_count} ✅</code>")
    bot.send_message(chat_id, txt, parse_mode='HTML')


@bot.message_handler(commands=['credits'])
def handle_credits(message):
    chat_id = message.chat.id
    if not check_user_joined(chat_id):
        prompt_join_channels(chat_id)
        return
    credits = get_user_credits(chat_id)
    mode = get_bot_mode()
    txt = f"💳 <b>BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\nBalance: <b>{'Unlimited' if mode == 'free' else credits} 💳</b>\nMode: <code>{mode.upper()}</code>"
    if credits <= 0 and mode == "paid":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("👨‍💻 Contact Admin",
                                              url=f"https://t.me/{DEVELOPER_USERNAME.lstrip('@')}"))
        bot.send_message(chat_id, txt, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, txt, parse_mode='HTML')


@bot.message_handler(commands=['refer'])
def handle_refer(message):
    chat_id = message.chat.id
    if not check_user_joined(chat_id):
        prompt_join_channels(chat_id)
        return
    try:
        bot_username = bot.get_me().username
    except Exception:
        bot_username = "bot"
    link = f"https://t.me/{bot_username}?start=ref_{chat_id}"
    data = load_stats()
    referred = sum(1 for u in data.get("users", []) if isinstance(u, dict) and u.get("referred_by") == chat_id)
    txt = (f"🤝 <b>REFERRAL</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
           f"Invite friends & earn 1 credit each!\n\n🔗 <code>{link}</code>\n\n👥 Referred: <code>{referred}</code>")
    bot.send_message(chat_id, txt, parse_mode='HTML')


@bot.message_handler(commands=['admin'])
def handle_admin(message):
    chat_id = message.chat.id
    if chat_id not in ADMIN_IDS:
        bot.send_message(chat_id, "❌ Access Denied!", parse_mode='HTML')
        return
    send_admin_dashboard(chat_id)


def perform_broadcast(message):
    admin_chat_id = message.chat.id
    data = load_stats()
    users = data.get("users", [])
    if not users:
        bot.send_message(admin_chat_id, "⚠️ No users.", parse_mode='HTML')
        return
    success = failed = 0
    for u in users:
        uid = u.get("chat_id") if isinstance(u, dict) else u
        if not uid:
            continue
        try:
            bot.copy_message(chat_id=uid, from_chat_id=admin_chat_id, message_id=message.message_id)
            success += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
    bot.send_message(admin_chat_id, f"✅ Broadcast done. Success: {success}, Failed: {failed}", parse_mode='HTML')


# ============================================================
# SECTION 13: MESSAGE HANDLER
# ============================================================
@bot.message_handler(content_types=['text', 'photo', 'audio', 'video', 'document', 'sticker',
                                     'voice', 'location', 'contact', 'video_note', 'animation'])
def handle_all(message):
    chat_id = message.chat.id
    try:
        register_visit(chat_id)
    except Exception:
        pass
    if message.text and message.text.strip().startswith('/start'):
        return
    if not check_user_joined(chat_id):
        prompt_join_channels(chat_id)
        return
    state = user_states.get(chat_id, {})
    str_chat_id = str(chat_id)

    # Broadcast interceptor
    if state.get('step') == 'AWAITING_BROADCAST_MSG':
        if message.text and message.text.strip().lower() == 'cancel':
            user_states[chat_id] = {'step': 'IDLE'}
            bot.send_message(chat_id, "❌ Cancelled.", reply_markup=types.ReplyKeyboardRemove())
            send_admin_dashboard(chat_id)
            return
        user_states[chat_id] = {'step': 'IDLE'}
        bot.send_message(chat_id, "🚀 Broadcasting...", reply_markup=types.ReplyKeyboardRemove())
        threading.Thread(target=perform_broadcast, args=(message,), daemon=True).start()
        return

    if not message.text:
        return
    text = message.text.strip()

    # Admin config interceptors
    if state.get('step') == 'AWAITING_ADMIN_COOLDOWN':
        if text.lower() == 'cancel':
            user_states[chat_id] = {'step': 'IDLE'}
            bot.send_message(chat_id, "❌ Cancelled.", reply_markup=types.ReplyKeyboardRemove())
            send_admin_dashboard(chat_id)
            return
        if not text.isdigit():
            bot.send_message(chat_id, "⚠️ Enter a number:", parse_mode='HTML')
            return
        set_cooldown_seconds(int(text))
        user_states[chat_id] = {'step': 'IDLE'}
        bot.send_message(chat_id, f"✅ Cooldown set to {text}s.", reply_markup=types.ReplyKeyboardRemove(), parse_mode='HTML')
        send_admin_dashboard(chat_id)
        return
    if state.get('step') == 'AWAITING_ADMIN_MAX_CONCURRENT':
        if text.lower() == 'cancel':
            user_states[chat_id] = {'step': 'IDLE'}
            bot.send_message(chat_id, "❌ Cancelled.", reply_markup=types.ReplyKeyboardRemove())
            send_admin_dashboard(chat_id)
            return
        if not text.isdigit():
            bot.send_message(chat_id, "⚠️ Enter a number:", parse_mode='HTML')
            return
        set_max_concurrent_tasks(int(text))
        user_states[chat_id] = {'step': 'IDLE'}
        bot.send_message(chat_id, f"✅ Max concurrent set to {text}.", reply_markup=types.ReplyKeyboardRemove(), parse_mode='HTML')
        send_admin_dashboard(chat_id)
        return
    if state.get('step') == 'AWAITING_ADMIN_DEFAULT_CREDITS':
        if text.lower() == 'cancel':
            user_states[chat_id] = {'step': 'IDLE'}
            bot.send_message(chat_id, "❌ Cancelled.", reply_markup=types.ReplyKeyboardRemove())
            send_admin_dashboard(chat_id)
            return
        if not text.isdigit():
            bot.send_message(chat_id, "⚠️ Enter a number:", parse_mode='HTML')
            return
        set_default_credits(int(text))
        user_states[chat_id] = {'step': 'IDLE'}
        bot.send_message(chat_id, f"✅ Default credits set to {text}.", reply_markup=types.ReplyKeyboardRemove(), parse_mode='HTML')
        send_admin_dashboard(chat_id)
        return
    if state.get('step') == 'AWAITING_ADMIN_GRANT_USER_ID':
        if text.lower() == 'cancel':
            user_states[chat_id] = {'step': 'IDLE'}
            bot.send_message(chat_id, "❌ Cancelled.", reply_markup=types.ReplyKeyboardRemove())
            send_admin_dashboard(chat_id)
            return
        if not text.lstrip('-').isdigit():
            bot.send_message(chat_id, "⚠️ Invalid ID.", parse_mode='HTML')
            return
        target_id = int(text)
        target_credits = get_user_credits(target_id)
        target_data = load_stats()
        target_record = None
        for u in target_data.get("users", []):
            if isinstance(u, dict) and str(u.get("chat_id")) == str(target_id):
                target_record = u
                break
        target_name = target_record.get("first_name", "N/A") if target_record else "N/A"
        target_uname = target_record.get("username", "N/A") if target_record else "N/A"
        user_states[chat_id] = {'step': 'AWAITING_ADMIN_GRANT_AMOUNT', 'target_user_id': target_id}
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Cancel")
        info = (f"➕ Grant credits to {target_name} (@{target_uname})\nID: <code>{target_id}</code>\n"
                f"Current credits: <code>{target_credits}</code>\n\nEnter amount (e.g. 5 or -2):")
        bot.send_message(chat_id, info, reply_markup=markup, parse_mode='HTML')
        return
    if state.get('step') == 'AWAITING_ADMIN_GRANT_AMOUNT':
        if text.lower() == 'cancel':
            user_states[chat_id] = {'step': 'IDLE'}
            bot.send_message(chat_id, "❌ Cancelled.", reply_markup=types.ReplyKeyboardRemove())
            send_admin_dashboard(chat_id)
            return
        is_neg = text.startswith('-')
        clean = text[1:] if is_neg else text
        if not clean.isdigit():
            bot.send_message(chat_id, "⚠️ Invalid amount.", parse_mode='HTML')
            return
        amount = int(clean)
        if is_neg:
            amount = -amount
        target_id = state.get('target_user_id')
        new_bal = add_user_credits(target_id, amount)
        user_states[chat_id] = {'step': 'IDLE'}
        try:
            if amount > 0:
                bot.send_message(target_id, f"🎉 +{amount} credits added! New balance: {new_bal}", parse_mode='HTML')
            else:
                bot.send_message(target_id, f"⚠️ {amount} credits updated. New balance: {new_bal}", parse_mode='HTML')
        except Exception:
            pass
        bot.send_message(chat_id, f"✅ Updated user {target_id}. New balance: {new_bal}",
                         reply_markup=types.ReplyKeyboardRemove(), parse_mode='HTML')
        send_admin_dashboard(chat_id)
        return

    # Cancel
    if text.lower() in ['/cancel', 'cancel', 'reset', '/reset']:
        if str_chat_id in user_page_registry:
            user_page_registry[str_chat_id]['value'] = '__CANCEL__'
        buffered_inputs.pop(str_chat_id, None)
        if str_chat_id in active_engines:
            eng = active_engines.pop(str_chat_id, None)
            if eng:
                try:
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(eng.close(), loop)
                except Exception:
                    pass
        if str_chat_id in active_tasks:
            try:
                active_tasks.remove(str_chat_id)
            except Exception:
                pass
        user_states[chat_id] = {'step': 'IDLE'}
        bot.send_message(chat_id, "❌ Cancelled.", parse_mode='HTML')
        send_welcome_dashboard(chat_id)
        return

    # Target mobile extraction
    is_group = chat_id < 0
    starts_with_cmd = text.lower().startswith(('/aadhaar', '/aadhar'))
    extracted = None
    if is_group:
        if starts_with_cmd:
            cmd_len = len('/aadhaar') if text.lower().startswith('/aadhaar') else len('/aadhar')
            number_part = text[cmd_len:].strip()
            clean = re.sub(r'\D', '', number_part)
            if len(clean) == 10 and clean[0] in '6789':
                extracted = clean
            elif len(clean) > 10 and (number_part.startswith('+91') or clean.startswith(('91', '0'))):
                possible = clean[-10:]
                if possible[0] in '6789':
                    extracted = possible
    else:
        if starts_with_cmd:
            cmd_len = len('/aadhaar') if text.lower().startswith('/aadhaar') else len('/aadhar')
            number_part = text[cmd_len:].strip()
            clean = re.sub(r'\D', '', number_part)
            if len(clean) == 10 and clean[0] in '6789':
                extracted = clean
            elif len(clean) > 10 and (number_part.startswith('+91') or clean.startswith(('91', '0'))):
                possible = clean[-10:]
                if possible[0] in '6789':
                    extracted = possible
        else:
            clean = re.sub(r'\D', '', text)
            if len(clean) == 10 and clean[0] in '6789':
                extracted = clean
            elif len(clean) > 10 and (text.startswith('+91') or clean.startswith(('91', '0'))):
                possible = clean[-10:]
                if possible[0] in '6789':
                    extracted = possible

    if extracted:
        if get_bot_mode() == "paid" and get_user_credits(chat_id) <= 0:
            send_zero_credits_dashboard(chat_id)
            return
        cached = find_cracked_record(extracted)
        if cached:
            if get_bot_mode() == "paid":
                deduct_user_credit(chat_id)
            name = cached.get("name", "N/A")
            uid = cached.get("uid", "N/A")
            pwd = cached.get("password", "N/A")
            eid = cached.get("eid", "N/A")
            txt = (f"🎉 <b>Found in cache!</b>\n\n👤 Name: <code>{name}</code>\n"
                   f"📞 Mobile: <code>{extracted}</code>\n🔢 Aadhaar: <code>{uid}</code>\n"
                   f"🔑 Password: <code>{pwd}</code>\n\n⚡ Instant retrieval.")
            bot.send_message(chat_id, txt, parse_mode='HTML')
            try:
                safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
                safe_uid = uid.replace(' ', '')
                pdf_path = os.path.join(CRACKED_DIR, f"{safe_name}_{safe_uid}.pdf")
                if os.path.exists(pdf_path):
                    with open(pdf_path, 'rb') as f:
                        bot.send_document(chat_id, f, caption="📄 PDF (Unlocked)")
            except Exception:
                pass
            send_welcome_dashboard(chat_id)
            return

        user_page_registry.pop(str_chat_id, None)
        buffered_inputs.pop(str_chat_id, None)
        if str_chat_id in active_engines:
            eng = active_engines.pop(str_chat_id, None)
            if eng:
                try:
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(eng.close(), loop)
                except Exception:
                    pass
        if str_chat_id in active_tasks:
            try:
                active_tasks.remove(str_chat_id)
            except Exception:
                pass
        prewarm_engine(bot, chat_id, extracted)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("👨 Male", callback_data="mp|Mr."),
            types.InlineKeyboardButton("👩 Female", callback_data="mp|Mrs."),
            types.InlineKeyboardButton("✏️ Manual", callback_data="mp|manual")
        )
        txt = get_ui_card(2, "Gender", "Select prefix:", target=extracted)
        bot.send_message(chat_id, txt, reply_markup=markup, parse_mode='HTML')
        user_states[chat_id] = {'step': 'AWAITING_MANUAL_PREF_SELECTION', 'num': extracted}
        return

    # Captcha/OTP input to engine
    if str_chat_id in user_page_registry and user_page_registry[str_chat_id].get('value') is None:
        user_page_registry[str_chat_id]['value'] = text
        if chat_id < 0:
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass
        return
    elif state.get('step') == 'PROCESSING':
        buffered_inputs[str_chat_id] = text
        if chat_id < 0:
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass
        return

    if state.get('step') == 'AWAITING_NAME':
        prefix = state.get('prefix', '')
        name = f"{prefix}{text}".strip()
        num = state.get('num', '')
        user_states[chat_id]['step'] = 'PROCESSING'
        user_info = {
            'username': message.from_user.username or 'N/A',
            'first_name': message.from_user.first_name or 'N/A'
        }
        global loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                execute_and_reset(chat_id, name, num, None, user_info=user_info), loop
            )
        return


async def execute_and_reset(chat_id, name, num, dob, user_info=None):
    task_started = False
    try:
        if get_bot_mode() == "paid" and get_user_credits(chat_id) <= 0:
            send_zero_credits_dashboard(chat_id)
            user_states[chat_id] = {'step': 'IDLE'}
            return
        if chat_id not in ADMIN_IDS:
            allowed, rem = check_global_cooldown()
            if not allowed:
                bot.send_message(chat_id, f"⏳ Cooldown active. Wait {rem}s.", parse_mode='HTML')
                user_states[chat_id] = {'step': 'IDLE'}
                send_welcome_dashboard(chat_id)
                return
            update_global_run_time()
        task_started = await execute_task(bot, chat_id, name, num, dob, user_info=user_info)
    except Exception as e:
        print(f"❌ execute error: {e}")
        try:
            log_error(chat_id, user_info, f"execute: {e}")
        except Exception:
            pass
    finally:
        if task_started:
            user_states[chat_id] = {'step': 'IDLE'}
            try:
                send_welcome_dashboard(chat_id)
            except Exception:
                pass


def cleanup_temp_files():
    print("🧹 Cleaning temp files...")
    for f in os.listdir(BASE_DIR):
        if f.startswith(('temp_captcha_', 'cap_ui_', 'cap_um_')):
            try:
                os.remove(os.path.join(BASE_DIR, f))
                print(f"🗑️ Removed {f}")
            except Exception:
                pass
    os.makedirs(CRACKED_DIR, exist_ok=True)


# ============================================================
# SECTION 14: ✅ RENDER HEALTH CHECK HTTP SERVER
# ============================================================
def start_health_server():
    """
    Render Web Service এর জন্য HTTP endpoint।
    এটা ছাড়া Render 503 Service Unavailable দিবে এবং বোট চালু থাকবে না।
    """
    port = int(os.environ.get("PORT", 8080))

    class HealthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK - Aadhaar Bot is running")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            pass  # স্কিল করো, লগ স্প্যাম হবে না

    class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    try:
        with ThreadedTCPServer(("0.0.0.0", port), HealthHandler) as httpd:
            print(f"✅ Health check server running on port {port}")
            httpd.serve_forever()
    except Exception as e:
        print(f"❌ Health server failed: {e}")


# ============================================================
# SECTION 15: MAIN ENTRY POINT
# ============================================================
if __name__ == "__main__":
    cleanup_temp_files()

    # Health server for Render (daemon thread)
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    # Asyncio loop in background thread
    loop = asyncio.new_event_loop()

    def run_loop(l):
        asyncio.set_event_loop(l)
        l.run_until_complete(init_pool(bot))
        l.run_forever()

    threading.Thread(target=run_loop, args=(loop,), daemon=True).start()

    # Wait a moment for health server to bind
    time.sleep(1)
    print("🤖 Bot is LIVE (Render Ready).")

    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30,
                                 skip_pending=True,
                                 allowed_updates=['message', 'callback_query'])
        except Exception as e:
            print(f"⚠️ Polling error: {e}")
            time.sleep(3)