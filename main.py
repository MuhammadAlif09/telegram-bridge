"""
main.py -- Entry point Antigravity <-> Telegram Bridge
Jalankan: python main.py
"""
import sys
import io
import os
# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import asyncio
import threading
import time
from config import BOT_TOKEN, CHAT_ID, ALLOWED_USER_IDS
from session_manager import SessionManager
from transcript_watcher import TranscriptWatcher
import telegram_handler

# ── Singleton lock (prevent duplicate instances) ──
LOCK_FILE = os.path.join(os.path.dirname(__file__), ".bridge.lock")


def _acquire_lock():
    """Prevent multiple bridge instances."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # Check if process still running (Windows)
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400, False, old_pid)  # PROCESS_QUERY_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                print(f"[Lock] Instance lama (PID {old_pid}) masih jalan. Matikan dulu!")
                sys.exit(1)
        except (ValueError, OSError, AttributeError):
            pass  # stale lock
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def _release_lock():
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass


def _send_raw(text: str, parse_mode: str = "HTML"):
    """Direct send to Telegram (bypass buffer). For startup/system messages."""
    import requests
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }, timeout=10)
        if not resp.ok:
            requests.post(url, json={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            }, timeout=10)
    except Exception as e:
        print(f"[Telegram] Send error: {e}")


def main():
    _acquire_lock()

    print("=" * 50)
    print("  Antigravity <-> Telegram Bridge")
    print("=" * 50)

    # 1. Init session manager
    session_mgr = SessionManager()
    auto_ok = session_mgr.auto_detect_active()
    if auto_ok:
        print(f"[Session] Active: {session_mgr.active_conv_id}")
    else:
        print("[Session] WARNING: No Antigravity sessions found!")

    # 2. Build telegram app
    tg_app = telegram_handler.build_app()

    # 3. Setup transcript watcher with debounce buffer & live bubble update
    import requests as _requests

    _current_compact: str = ""
    _accumulated_details: list[str] = []
    _buffer_lock = threading.Lock()
    _flush_timer: threading.Timer | None = None
    _last_message_id = None
    _last_actions: list[str] = []
    
    # 1.5 seconds is perfect for real-time live feeling without hitting limits
    DEBOUNCE_SECONDS = 1.5

    def _flush_buffer():
        """Send/edit Telegram bubble with the latest compact text and action buttons."""
        nonlocal _flush_timer, _last_message_id
        with _buffer_lock:
            if not _current_compact:
                return
            combined = _current_compact
            _flush_timer = None

        # Truncate to Telegram's 4096 char limit
        if len(combined) > 4000:
            combined = combined[:3900] + "\n\n<i>[Truncated...]</i>"

        # Build dynamic reply markup (action buttons)
        has_git = False
        try:
            from config import PROJECT_DIR
            import subprocess
            res = subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=2)
            has_git = bool(res.stdout.strip())
        except Exception:
            pass

        inline_keyboard = []

        # Row 1: Action approvals (visible only when actions are pending)
        action_row = []
        if "y" in _last_actions:
            action_row.append({"text": "✅ Approve (y)", "callback_data": "action_approve_y"})
        if "n" in _last_actions:
            action_row.append({"text": "❌ Reject (n)", "callback_data": "action_reject_n"})
        if "proceed" in _last_actions:
            action_row.append({"text": "🚀 Proceed", "callback_data": "action_approve_proceed"})
        if action_row:
            inline_keyboard.append(action_row)

        # Row 2: Multiple choice option selectors (visible only when options are expected)
        if "options" in _last_actions:
            inline_keyboard.append([
                {"text": "1️⃣", "callback_data": "action_option_1"},
                {"text": "2️⃣", "callback_data": "action_option_2"},
                {"text": "3️⃣", "callback_data": "action_option_3"}
            ])

        # Row 3: Git diff & Tool Steps (dynamic based on changes/steps)
        view_row = []
        if has_git:
            view_row.append({"text": "🔍 Git Diff", "callback_data": "action_git_diff"})
        
        # Only show tool steps button if we accumulated details in this turn
        if _accumulated_details:
            full_detail_text = "\n\n───────────────────\n\n".join(_accumulated_details)
            telegram_handler.set_last_tool_steps(full_detail_text)
            view_row.append({"text": "🛠 Tool Steps", "callback_data": "action_tool_steps"})
        else:
            telegram_handler.set_last_tool_steps("")

        if view_row:
            inline_keyboard.append(view_row)

        reply_markup = {"inline_keyboard": inline_keyboard} if inline_keyboard else None

        try:
            url_send = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            url_edit = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"

            payload = {
                "chat_id": CHAT_ID,
                "text": combined,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup

            if _last_message_id is None:
                # Send new message bubble
                resp = _requests.post(url_send, json=payload, timeout=10)
                if resp.ok:
                    data = resp.json()
                    _last_message_id = data.get("result", {}).get("message_id")
                else:
                    print(f"[Telegram] Send failed: {resp.text}")
            else:
                # Edit existing message bubble
                payload["message_id"] = _last_message_id
                resp = _requests.post(url_edit, json=payload, timeout=10)
                if not resp.ok:
                    err_desc = resp.json().get("description", "")
                    if "message is not modified" not in err_desc:
                        print(f"[Telegram] Edit failed: {err_desc}. Sending new bubble.")
                        _last_message_id = None
                        with _buffer_lock:
                            if not _flush_timer:
                                _flush_timer = threading.Timer(0.1, _flush_buffer)
                                _flush_timer.daemon = True
                                _flush_timer.start()
        except Exception as e:
            print(f"[Telegram] Flush error: {e}")

    def send_to_telegram(compact: str, detail: str | None = None, actions: list[str] | None = None):
        """Buffer message, flush after debounce. Overwrites compact, accumulates detail."""
        nonlocal _flush_timer, _last_message_id, _last_actions, _current_compact
        
        if compact == "__RESET__":
            if _flush_timer:
                _flush_timer.cancel()
                _flush_buffer()
            with _buffer_lock:
                _current_compact = ""
                _accumulated_details.clear()
                _last_message_id = None
                _flush_timer = None
            telegram_handler.set_last_tool_steps("")
            _last_actions = []
            print("[Watcher] User input detected. Resetting bubble.")
            return

        # Terapkan filter notifikasi berdasarkan pengaturan mode
        mode = telegram_handler.get_notification_mode()
        if compact != "__RESET__":
            if mode == "compact":
                # Mode Compact: Hanya kirim saat tugas selesai (actions == []) atau butuh persetujuan user (actions ada isinya)
                # Skip progress langkah per langkah (actions != [] tapi tidak butuh persetujuan, e.g. normal tool run)
                if actions != [] and not any(act in str(actions) for act in ["y", "n", "proceed", "options"]):
                    return
            elif mode == "silent":
                # Mode Silent: Hanya kirim jika benar-benar butuh persetujuan/input user
                if not actions or all(act not in str(actions) for act in ["y", "n", "proceed", "options"]):
                    return

        with _buffer_lock:
            if compact is not None:
                _current_compact = compact
            
            if detail and detail not in _accumulated_details:
                _accumulated_details.append(detail)
                
            if actions is not None:
                _last_actions = actions
                
            # Jika tugas selesai (tidak ada pending action), langsung kirim
            if actions == []:
                if _flush_timer is not None:
                    _flush_timer.cancel()
                    _flush_timer = None
                threading.Thread(target=_flush_buffer, daemon=True).start()
            else:
                # Sedang berjalan: batasi pengiriman agar tidak spam
                if _flush_timer is None:
                    _flush_timer = threading.Timer(DEBOUNCE_SECONDS, _flush_buffer)
                    _flush_timer.daemon = True
                    _flush_timer.start()

    watcher = TranscriptWatcher(on_new_message=send_to_telegram)

    if session_mgr.transcript_path:
        watcher.set_transcript(session_mgr.transcript_path)
        watcher.start()
        print(f"[Watcher] Watching: {session_mgr.transcript_path}")
    else:
        print("[Watcher] No transcript found, watcher on standby.")
        watcher.start()

    # 4. Inject dependencies
    telegram_handler.init(session_mgr, watcher)

    # 5. Send startup message
    def send_startup():
        time.sleep(2)
        active_id = session_mgr.active_conv_id or "None"
        short_id = active_id[:8] if active_id != "None" else "None"
        _send_raw(
            f"🟢 <b>Antigravity Bridge Online</b>\n\n"
            f"🔗 Session: <code>{short_id}...</code>\n"
            f"🤖 Ready to stream AI activity\n\n"
            f"Type /menu for controls."
        )

    threading.Thread(target=send_startup, daemon=True).start()

    # 6. Run bot
    print("[Bot] Telegram polling started...")
    print(f"[Bot] Allowed users: {ALLOWED_USER_IDS}")
    print("[Bot] Press Ctrl+C to stop.\n")

    async def run_bot():
        await telegram_handler.set_bot_commands(tg_app)
        async with tg_app:
            await tg_app.start()
            await tg_app.updater.start_polling(drop_pending_updates=True)
            stop_event = asyncio.Event()
            try:
                import signal
                loop = asyncio.get_event_loop()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    try:
                        loop.add_signal_handler(sig, stop_event.set)
                    except NotImplementedError:
                        pass
            except Exception:
                pass
            try:
                await stop_event.wait()
            except (KeyboardInterrupt, SystemExit):
                pass
            await tg_app.updater.stop()
            await tg_app.stop()

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass
    finally:
        _release_lock()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Bridge] Stopped.")
    except Exception as e:
        print(f"\n[Bridge] Fatal: {e}")
        raise
