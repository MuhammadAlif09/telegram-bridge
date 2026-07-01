"""
telegram_handler.py -- Telegram Bot with inline keyboards, professional formatting
All messages use HTML parse_mode for reliable rendering.
All emojis are literal unicode characters to prevent Windows encoding bugs.
"""
import asyncio
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

from config import BOT_TOKEN, CHAT_ID, ALLOWED_USER_IDS, NINEROUTER_ACCOUNTS
import ui_controller
from token_counter import (
    count_tokens_from_transcript, format_token_message_html,
    format_ninerouter_balance_html, ninerouter_keyboard
)

# Models available in Antigravity IDE
AVAILABLE_MODELS = [
    ("Gemini 3.5 Flash (Medium)", "gemini-35-flash-medium"),
    ("Gemini 3.5 Flash (High)", "gemini-35-flash-high"),
    ("Gemini 3.5 Flash (Low)", "gemini-35-flash-low"),
    ("Gemini 3.1 Pro (Low)", "gemini-31-pro-low"),
    ("Gemini 3.1 Pro (High)", "gemini-31-pro-high"),
    ("Claude Sonnet 4.6 (Thinking)", "claude-sonnet-46-thinking"),
    ("Claude Opus 4.6 (Thinking)", "claude-opus-46-thinking"),
    ("GPT-OSS 120B (Medium)", "gpt-oss-120b-medium"),
]

# Injected state
_session_manager = None
_transcript_watcher = None
_calibration_mode = False
_last_tool_steps = ""
_notification_mode = "real-time"


def get_notification_mode() -> str:
    return _notification_mode


def set_notification_mode(mode: str):
    global _notification_mode
    _notification_mode = mode


def init(session_manager, transcript_watcher):
    global _session_manager, _transcript_watcher
    _session_manager = session_manager
    _transcript_watcher = transcript_watcher


def set_last_tool_steps(text: str):
    global _last_tool_steps
    _last_tool_steps = text


def _auth(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    return uid in ALLOWED_USER_IDS


# ─── Keyboards ────────────────────────────────────────────────────────────────

def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Screen", callback_data="menu_screenshot"),
            InlineKeyboardButton("📋 Task", callback_data="menu_task"),
            InlineKeyboardButton("ℹ️ Status", callback_data="menu_status"),
        ],
        [
            InlineKeyboardButton("📁 Files", callback_data="menu_files"),
            InlineKeyboardButton("💻 CMDs", callback_data="menu_cmds"),
            InlineKeyboardButton("🌿 Git", callback_data="menu_git"),
        ],
        [
            InlineKeyboardButton("🤖 Model", callback_data="menu_model"),
            InlineKeyboardButton("📊 Tokens", callback_data="menu_token"),
            InlineKeyboardButton("📁 Sessions", callback_data="menu_sessions"),
        ],
        [
            InlineKeyboardButton("🆕 New Sess", callback_data="menu_new_session"),
            InlineKeyboardButton("🎯 Calibrate", callback_data="menu_calibrate"),
            InlineKeyboardButton("🔔 Notif", callback_data="menu_notif"),
        ]
    ])


def _model_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for name, key in AVAILABLE_MODELS:
        short_name = name.replace("Claude ", "").replace("Gemini ", "")
        row.append(InlineKeyboardButton(short_name, callback_data=f"model_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("← Back", callback_data="menu_back")])
    return InlineKeyboardMarkup(keyboard)


def _sessions_keyboard() -> InlineKeyboardMarkup:
    sessions = _session_manager.get_all_sessions()[:8]
    keyboard = []
    row = []
    for s in sessions:
        active = "🟢 " if s["id"] == _session_manager.active_conv_id else ""
        title = s["title"]
        if len(title) > 15:
            title = title[:12] + "..."
        label = f"{active}{title}"
        row.append(InlineKeyboardButton(label, callback_data=f"sess_{s['id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("← Back", callback_data="menu_back")])
    return InlineKeyboardMarkup(keyboard)


def _calibrate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 Chat Input Box", callback_data="menu_calibrate_input"),
        ],
        [
            InlineKeyboardButton("🤖 Model Dropdown", callback_data="menu_calibrate_model"),
        ],
        [
            InlineKeyboardButton("← Back", callback_data="menu_back"),
        ]
    ])


def _get_files_keyboard(current_relative_path: str = "") -> InlineKeyboardMarkup:
    from config import PROJECT_DIR
    from pathlib import Path
    base_dir = Path(PROJECT_DIR).resolve()
    target_dir = (base_dir / current_relative_path).resolve()
    
    # Keamanan: cegah directory traversal keluar dari PROJECT_DIR
    if not str(target_dir).startswith(str(base_dir)):
        target_dir = base_dir
        current_relative_path = ""
        
    keyboard = []
    
    # Tombol folder parent jika tidak di root
    if current_relative_path:
        parent_rel = str(Path(current_relative_path).parent)
        if parent_rel == ".":
            parent_rel = ""
        keyboard.append([InlineKeyboardButton("⬆️ Up (Parent Folder)", callback_data=f"files_dir_{parent_rel}")])
        
    try:
        items = list(target_dir.iterdir())
        items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
        
        ignored = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}
        row = []
        count = 0
        for item in items:
            if item.name in ignored or (item.name.startswith(".") and item.name != ".env"):
                continue
                
            rel_item_path = str(item.relative_to(base_dir)).replace("\\", "/")
            
            if item.is_dir():
                label = f"📁 {item.name}"
                callback_data = f"files_dir_{rel_item_path}"
            else:
                label = f"📄 {item.name}"
                callback_data = f"files_view_{rel_item_path}"
                
            row.append(InlineKeyboardButton(label, callback_data=callback_data))
            if len(row) == 2:
                keyboard.append(row)
                row = []
                
            count += 1
            if count >= 16:  # Batasi agar keyboard tidak kepanjangan
                break
                
        if row:
            keyboard.append(row)
            
    except Exception as e:
        keyboard.append([InlineKeyboardButton(f"❌ Error: {str(e)[:25]}", callback_data="menu_back")])
        
    keyboard.append([InlineKeyboardButton("← Back", callback_data="menu_back")])
    return InlineKeyboardMarkup(keyboard)


def _run_history_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("git status", callback_data="run_cmd_git_status"),
            InlineKeyboardButton("git diff", callback_data="run_cmd_git_diff")
        ],
        [
            InlineKeyboardButton("git branch", callback_data="run_cmd_git_branch"),
            InlineKeyboardButton("git log", callback_data="run_cmd_git_log")
        ],
        [
            InlineKeyboardButton("npm run dev", callback_data="run_cmd_npm_dev"),
            InlineKeyboardButton("python main.py", callback_data="run_cmd_python_main")
        ],
        [
            InlineKeyboardButton("← Back", callback_data="menu_back")
        ]
    ])


def _notification_settings_keyboard() -> InlineKeyboardMarkup:
    mode = get_notification_mode()
    m_real = "🟢 Real-time" if mode == "real-time" else "⚪ Real-time"
    m_comp = "🟢 Compact" if mode == "compact" else "⚪ Compact"
    m_sile = "🟢 Silent" if mode == "silent" else "⚪ Silent"
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(m_real, callback_data="notif_mode_real-time")],
        [InlineKeyboardButton(m_comp, callback_data="notif_mode_compact")],
        [InlineKeyboardButton(m_sile, callback_data="notif_mode_silent")],
        [InlineKeyboardButton("← Back", callback_data="menu_back")]
    ])


def _git_keyboard() -> InlineKeyboardMarkup:
    import subprocess
    from config import PROJECT_DIR
    current_branch = "unknown"
    other_branches = []
    try:
        res = subprocess.run(["git", "branch"], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=2)
        lines = res.stdout.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("*"):
                current_branch = line.replace("*", "").strip()
            else:
                other_branches.append(line.strip())
    except Exception:
        pass
        
    keyboard = []
    # Opsi checkout branch lain (maksimal 3)
    for b in other_branches[:3]:
        keyboard.append([InlineKeyboardButton(f"🌿 Switch to {b}", callback_data=f"git_checkout_{b}")])
        
    keyboard.append([
        InlineKeyboardButton("⬇️ Pull", callback_data="git_pull"),
        InlineKeyboardButton("⬆️ Push", callback_data="git_push")
    ])
    keyboard.append([InlineKeyboardButton("← Back", callback_data="menu_back")])
    return InlineKeyboardMarkup(keyboard)


# ─── Command Handlers ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        await update.message.reply_text("⛔ Access denied.")
        return

    active = _session_manager.active_conv_id
    short_id = f"<code>{active[:8]}...</code>" if active else "None"

    text = (
        f"🚀 <b>Antigravity Bridge</b>\n\n"
        f"🔗 Session: {short_id}\n"
        f"🤖 Send any message → auto-type to IDE\n\n"
        f"Use the menu below:"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=_main_menu_keyboard())


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    await update.message.reply_text(
        "🎛 <b>Control Panel</b>",
        parse_mode="HTML",
        reply_markup=_main_menu_keyboard()
    )


async def cmd_coords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    await update.message.reply_text(
        "⏳ <b>Kalibrasi dimulai!</b>\n\n"
        "Dalam <b>5 detik</b>, arahkan kursor mouse ke <b>kotak input chat</b> di IDE Antigravity dan diamkan di sana...",
        parse_mode="HTML"
    )
    await asyncio.sleep(5)
    x, y = ui_controller.get_current_cursor_pos()
    ui_controller.set_input_coords(x, y)
    await update.message.reply_text(
        f"✅ <b>Kalibrasi Berhasil!</b>\n\n"
        f"Koordinat input box disimpan: <code>({x}, {y})</code>.",
        parse_mode="HTML"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    await update.message.reply_text(_build_status_text(), parse_mode="HTML")


def _build_status_text() -> str:
    active = _session_manager.active_conv_id if _session_manager else None
    paused = _transcript_watcher._paused if _transcript_watcher else False
    calibrated = ui_controller._config["calibrated"]
    ide_found = ui_controller.find_ide_window()
    coords = f"({ui_controller._config['input_x']}, {ui_controller._config['input_y']})" if calibrated else "Not set"
    
    return (
        f"ℹ️ <b>Bridge Status</b>\n\n"
        f"🔗 Session: <code>{active[:8] if active else 'None'}...</code>\n"
        f"📡 Watcher: {'<b>⏸ Paused</b>' if paused else '🟢 Active'}\n"
        f"🎯 Coordinates: <code>{coords}</code>\n"
        f"🖥 IDE: {'🟢 Found' if ide_found else '🔴 Not found'}"
    )


async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    status_msg = await update.message.reply_text("📸 Taking screenshot...")
    try:
        import pyautogui
        import tempfile
        import os
        
        screenshot = pyautogui.screenshot()
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, "screenshot.png")
        screenshot.save(temp_path)
        
        with open(temp_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption="📸 IDE Screen Capture")
            
        await status_msg.delete()
        try:
            os.remove(temp_path)
        except Exception:
            pass
    except Exception as e:
        await status_msg.edit_text(f"❌ Failed to take screenshot: {e}")


async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
        
    from config import ANTIGRAVITY_BRAIN_DIR, PROJECT_DIR
    active_id = _session_manager.active_conv_id if _session_manager else None
    
    task_path = None
    if active_id:
        p = Path(ANTIGRAVITY_BRAIN_DIR) / active_id / "task.md"
        if p.exists():
            task_path = p
            
    if not task_path:
        p = Path(PROJECT_DIR) / "task.md"
        if p.exists():
            task_path = p
            
    if not task_path:
        await update.message.reply_text("ℹ️ Tidak menemukan file <code>task.md</code> di sesi aktif atau project.", parse_mode="HTML")
        return
        
    try:
        with open(task_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        formatted_lines = []
        for line in lines:
            line_str = line.strip()
            if not line_str:
                formatted_lines.append("")
                continue
                
            if line_str.startswith("- [x]") or line_str.startswith("- [X]"):
                formatted_lines.append("✅ " + line_str.split("]", 1)[1].strip())
            elif line_str.startswith("- [/]"):
                formatted_lines.append("⏳ " + line_str.split("]", 1)[1].strip())
            elif line_str.startswith("- [ ]"):
                formatted_lines.append("⬜ " + line_str.split("]", 1)[1].strip())
            else:
                formatted_lines.append(line_str)
                
        output = "\n".join(formatted_lines).strip()
        if not output:
            output = "ℹ️ File task.md kosong."
            
        await update.message.reply_text(
            f"📋 <b>Progress Task:</b>\n\n{output}",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal membaca task.md: {e}")


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
        
    if not context.args:
        await update.message.reply_text("ℹ️ Silakan tentukan command, contoh: <code>/run git status</code>", parse_mode="HTML")
        return
        
    cmd_str = " ".join(context.args)
    status_msg = await update.message.reply_text(f"💻 Running: <code>{cmd_str}</code>...", parse_mode="HTML")
    
    import subprocess
    from config import PROJECT_DIR
    try:
        res = subprocess.run(
            cmd_str,
            cwd=PROJECT_DIR,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15
        )
        
        output = ""
        if res.stdout:
            output += res.stdout
        if res.stderr:
            output += f"\n[Stderr]\n{res.stderr}"
            
        output = output.strip()
        if not output:
            output = "[Command finished with no output]"
            
        from transcript_watcher import _esc
        escaped = _esc(output)
        if len(escaped) > 4000:
            escaped = escaped[:3900] + "\n\n<i>[Output truncated...]</i>"
            
        await status_msg.edit_text(
            f"💻 <b>Execution Output:</b>\n"
            f"<pre><code class=\"language-powershell\">{escaped}</code></pre>",
            parse_mode="HTML"
        )
    except subprocess.TimeoutExpired:
        await status_msg.edit_text(f"⏳ Command timed out after 15 seconds.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Failed to execute command: {e}")


async def cmd_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
        
    if not context.args:
        await update.message.reply_text("ℹ️ Silakan tentukan nama file, contoh: <code>/view main.py</code>", parse_mode="HTML")
        return
        
    filename = context.args[0]
    from config import PROJECT_DIR
    
    try:
        proj_path = Path(PROJECT_DIR).resolve()
        target_path = (proj_path / filename).resolve()
        
        if not str(target_path).startswith(str(proj_path)):
            await update.message.reply_text("❌ Akses ditolak: File di luar direktori project.")
            return
            
        if not target_path.exists():
            await update.message.reply_text(f"❌ File tidak ditemukan: <code>{filename}</code>", parse_mode="HTML")
            return
            
        if not target_path.is_file():
            await update.message.reply_text(f"❌ Target bukan file: <code>{filename}</code>", parse_mode="HTML")
            return
            
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            
        lines = content.split("\n")
        truncated = False
        if len(lines) > 150:
            content = "\n".join(lines[:150])
            truncated = True
            
        from transcript_watcher import _esc
        escaped = _esc(content.strip())
        if len(escaped) > 3800:
            escaped = escaped[:3700]
            truncated = True
            
        suffix = "\n\n<i>[File truncated, showing first 150 lines]</i>" if truncated else ""
        
        await update.message.reply_text(
            f"📂 <b>File: {filename}</b>\n"
            f"<pre><code>{escaped}</code></pre>{suffix}",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal membaca file: {e}")


# ─── Callback Query Handler ───────────────────────────────────────────────────

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _calibration_mode
    query = update.callback_query
    await query.answer()

    if not _auth(update):
        await query.edit_message_text("⛔ Access denied.")
        return

    data = query.data

    if data == "menu_back":
        await query.edit_message_text(
            "🎛 <b>Control Panel</b>",
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard()
        )

    elif data == "menu_model":
        await query.edit_message_text(
            "🤖 <b>Select Model</b>",
            parse_mode="HTML",
            reply_markup=_model_keyboard()
        )

    elif data == "menu_token":
        accounts = NINEROUTER_ACCOUNTS or [
            {
                "account_name": "Akun Antigravity (Personal)",
                "estimated_usd": 185.50,
                "models": [
                    {"model_name": "Claude 3.5 Sonnet", "token_left": 4250000, "token_total": 10000000},
                    {"model_name": "Gemini 1.5 Pro", "token_left": 18400000, "token_total": 20000000},
                    {"model_name": "GPT-4o", "token_left": 800000, "token_total": 2000000}
                ]
            },
            {
                "account_name": "Akun Office (Corporate)",
                "estimated_usd": 94.20,
                "models": [
                    {"model_name": "Claude 3.5 Sonnet", "token_left": 1200000, "token_total": 5000000},
                    {"model_name": "Llama 3 70B", "token_left": 8200000, "token_total": 10000000}
                ]
            },
            {
                "account_name": "Akun Developer (Testing)",
                "estimated_usd": 15.00,
                "models": [
                    {"model_name": "Gemini 1.5 Flash", "token_left": 4500000, "token_total": 5000000}
                ]
            }
        ]
        total_pages = len(accounts)
        text = format_ninerouter_balance_html(accounts[0], 0, total_pages)
        buttons = ninerouter_keyboard(0, total_pages)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row]
            for row in buttons
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "menu_new_session":
        result = ui_controller.type_message_to_ide("/new")
        if result["success"]:
            await query.edit_message_text(
                "🆕 <b>New session command sent to IDE</b>\n\n"
                "Use 📁 Sessions to switch after it's created.",
                parse_mode="HTML",
                reply_markup=_main_menu_keyboard()
            )
        else:
            await query.edit_message_text(
                f"❌ Failed: {result['error']}",
                reply_markup=_main_menu_keyboard()
            )

    elif data == "menu_sessions":
        sessions = _session_manager.get_all_sessions()
        if not sessions:
            await query.edit_message_text("❌ No sessions found.", reply_markup=_main_menu_keyboard())
            return
        await query.edit_message_text(
            "📁 <b>Select Session</b>\n\n🟢 = currently active",
            parse_mode="HTML",
            reply_markup=_sessions_keyboard()
        )

    elif data == "menu_files":
        await query.edit_message_text(
            "📁 <b>File Explorer</b>\n\n"
            "Jelajahi folder project saat ini:",
            parse_mode="HTML",
            reply_markup=_get_files_keyboard("")
        )

    elif data.startswith("files_dir_"):
        rel_path = data[len("files_dir_"):]
        await query.edit_message_text(
            f"📁 <b>Folder:</b> <code>{rel_path or '/'}</code>",
            parse_mode="HTML",
            reply_markup=_get_files_keyboard(rel_path)
        )

    elif data.startswith("files_view_"):
        rel_path = data[len("files_view_"):]
        await query.answer("Reading file...")
        try:
            from config import PROJECT_DIR
            full_path = os.path.join(PROJECT_DIR, rel_path)
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            
            truncated = False
            if len(lines) > 150:
                lines = lines[:150]
                truncated = True
            content = "".join(lines)
            
            from transcript_watcher import _esc
            escaped = _esc(content.strip())
            if len(escaped) > 3800:
                escaped = escaped[:3700]
                truncated = True
                
            suffix = "\n\n<i>[File truncated, showing first 150 lines]</i>" if truncated else ""
            
            # Send file content as a new message so the explorer bubble remains active!
            await query.message.reply_text(
                f"📄 <b>File: {os.path.basename(rel_path)}</b>\n"
                f"<pre><code>{escaped}</code></pre>{suffix}",
                parse_mode="HTML"
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Gagal membaca file: {e}")

    elif data == "menu_cmds":
        await query.edit_message_text(
            "💻 <b>Terminal CMD History</b>\n\n"
            "Pilih perintah untuk dijalankan di background:",
            parse_mode="HTML",
            reply_markup=_run_history_keyboard()
        )

    elif data.startswith("run_cmd_"):
        cmd_key = data[len("run_cmd_"):]
        cmd_map = {
            "git_status": "git status",
            "git_diff": "git diff",
            "git_branch": "git branch",
            "git_log": "git log -n 5",
            "npm_dev": "npm run dev",
            "python_main": "python main.py"
        }
        cmd = cmd_map.get(cmd_key)
        if cmd:
            await query.answer(f"Running: {cmd}...")
            await query.edit_message_text(
                f"⏳ <b>Running:</b> <code>{cmd}</code>\n\n"
                f"Mengeksekusi perintah di terminal, mohon tunggu...",
                parse_mode="HTML"
            )
            # Jalankan command
            import subprocess
            from config import PROJECT_DIR
            try:
                # Batasi timeout 5 detik
                res = subprocess.run(cmd.split(), cwd=PROJECT_DIR, capture_output=True, text=True, timeout=5)
                out = (res.stdout + "\n" + res.stderr).strip()
                if not out:
                    out = "[No output]"
                if len(out) > 3800:
                    out = out[:3700] + "\n...[output truncated]"
                
                await query.edit_message_text(
                    f"💻 <b>Command:</b> <code>{cmd}</code>\n\n"
                    f"<pre><code>{out}</code></pre>",
                    parse_mode="HTML",
                    reply_markup=_main_menu_keyboard()
                )
            except Exception as e:
                await query.edit_message_text(
                    f"❌ <b>Gagal menjalankan:</b> <code>{cmd}</code>\n"
                    f"Error: <code>{e}</code>",
                    parse_mode="HTML",
                    reply_markup=_main_menu_keyboard()
                )

    elif data == "menu_notif":
        await query.edit_message_text(
            "🔔 <b>Notification Settings</b>\n\n"
            "Pilih tingkat notifikasi bot Telegram:\n\n"
            "• <b>Real-time</b>: Kirim setiap perubahan langkah AI\n"
            "• <b>Compact</b>: Kirim hanya ringkasan saat tugas selesai\n"
            "• <b>Silent</b>: Kirim hanya saat butuh izin persetujuan",
            parse_mode="HTML",
            reply_markup=_notification_settings_keyboard()
        )

    elif data.startswith("notif_mode_"):
        mode = data[len("notif_mode_"):]
        set_notification_mode(mode)
        await query.answer(f"Notification mode: {mode}")
        await query.edit_message_text(
            f"✅ <b>Notifikasi diubah ke: {mode.capitalize()}</b>",
            parse_mode="HTML",
            reply_markup=_notification_settings_keyboard()
        )

    elif data == "menu_git":
        await query.edit_message_text(
            "🌿 <b>Git Control Center</b>\n\n"
            "Pilih opsi repositori Git:",
            parse_mode="HTML",
            reply_markup=_git_keyboard()
        )

    elif data.startswith("git_checkout_"):
        branch = data[len("git_checkout_"):]
        await query.answer(f"Checking out: {branch}...")
        import subprocess
        from config import PROJECT_DIR
        res = subprocess.run(["git", "checkout", branch], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=5)
        out = (res.stdout + "\n" + res.stderr).strip()
        await query.edit_message_text(
            f"🌿 <b>Git Checkout: {branch}</b>\n\n"
            f"<pre><code>{out}</code></pre>",
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard()
        )

    elif data == "git_pull":
        await query.answer("Git pulling...")
        await query.edit_message_text("⏳ <b>Git pulling...</b>", parse_mode="HTML")
        import subprocess
        from config import PROJECT_DIR
        res = subprocess.run(["git", "pull"], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=10)
        out = (res.stdout + "\n" + res.stderr).strip()
        await query.edit_message_text(
            f"⬇️ <b>Git Pull</b>\n\n"
            f"<pre><code>{out}</code></pre>",
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard()
        )

    elif data == "git_push":
        await query.answer("Git pushing...")
        await query.edit_message_text("⏳ <b>Git pushing...</b>", parse_mode="HTML")
        import subprocess
        from config import PROJECT_DIR
        res = subprocess.run(["git", "push"], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=15)
        out = (res.stdout + "\n" + res.stderr).strip()
        await query.edit_message_text(
            f"⬆️ <b>Git Push</b>\n\n"
            f"<pre><code>{out}</code></pre>",
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard()
        )

    elif data == "menu_calibrate":
        await query.edit_message_text(
            "🎯 <b>UI Calibration Settings</b>\n\n"
            "Pilih elemen IDE yang ingin dikalibrasi:",
            parse_mode="HTML",
            reply_markup=_calibrate_keyboard()
        )

    elif data == "menu_calibrate_input":
        await query.edit_message_text(
            "⏳ <b>Kalibrasi Input Box dimulai!</b>\n\n"
            "Dalam <b>5 detik</b>, arahkan kursor mouse ke <b>kotak input chat</b> di IDE Antigravity dan diamkan...",
            parse_mode="HTML"
        )
        await asyncio.sleep(5)
        x, y = ui_controller.get_current_cursor_pos()
        ui_controller.set_input_coords(x, y)
        await query.edit_message_text(
            f"✅ <b>Kalibrasi Input Box Berhasil!</b>\n\n"
            f"Koordinat disimpan: <code>({x}, {y})</code>.\n"
            f"Sekarang bot akan mengklik posisi ini sebelum mengetik.",
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard()
        )

    elif data == "menu_calibrate_model":
        await query.edit_message_text(
            "⏳ <b>Kalibrasi Model Dropdown dimulai!</b>\n\n"
            "Dalam <b>5 detik</b>, arahkan kursor mouse ke <b>model dropdown</b> (di bagian atas chat IDE Antigravity) dan diamkan...",
            parse_mode="HTML"
        )
        await asyncio.sleep(5)
        x, y = ui_controller.get_current_cursor_pos()
        ui_controller.set_model_coords(x, y)
        await query.edit_message_text(
            f"✅ <b>Kalibrasi Model Dropdown Berhasil!</b>\n\n"
            f"Koordinat disimpan: <code>({x}, {y})</code>.\n"
            f"Sekarang bot akan mengklik posisi ini untuk mengganti model.",
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard()
        )

    elif data == "menu_status":
        await query.edit_message_text(
            _build_status_text(),
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard()
        )

    elif data == "menu_screenshot":
        await query.answer("📸 Taking screenshot...")
        try:
            import pyautogui
            import tempfile
            import os
            screenshot = pyautogui.screenshot()
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, "screenshot.png")
            screenshot.save(temp_path)
            
            with open(temp_path, "rb") as photo:
                await query.message.reply_photo(photo=photo, caption="📸 IDE Screen Capture")
                
            try:
                os.remove(temp_path)
            except Exception:
                pass
        except Exception as e:
            await query.message.reply_text(f"❌ Failed to take screenshot: {e}")

    elif data == "menu_task":
        await query.answer("📋 Reading task.md...")
        from config import ANTIGRAVITY_BRAIN_DIR, PROJECT_DIR
        active_id = _session_manager.active_conv_id if _session_manager else None
        
        task_path = None
        if active_id:
            p = Path(ANTIGRAVITY_BRAIN_DIR) / active_id / "task.md"
            if p.exists():
                task_path = p
                
        if not task_path:
            p = Path(PROJECT_DIR) / "task.md"
            if p.exists():
                task_path = p
                
        if not task_path:
            await query.message.reply_text("ℹ️ Tidak menemukan file <code>task.md</code> di sesi aktif atau project.", parse_mode="HTML")
            return
            
        try:
            with open(task_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            formatted_lines = []
            for line in lines:
                line_str = line.strip()
                if not line_str:
                    formatted_lines.append("")
                    continue
                    
                if line_str.startswith("- [x]") or line_str.startswith("- [X]"):
                    formatted_lines.append("✅ " + line_str.split("]", 1)[1].strip())
                elif line_str.startswith("- [/]"):
                    formatted_lines.append("⏳ " + line_str.split("]", 1)[1].strip())
                elif line_str.startswith("- [ ]"):
                    formatted_lines.append("⬜ " + line_str.split("]", 1)[1].strip())
                else:
                    formatted_lines.append(line_str)
                    
            output = "\n".join(formatted_lines).strip()
            if not output:
                output = "ℹ️ File task.md kosong."
                
            await query.message.reply_text(
                f"📋 <b>Progress Task:</b>\n\n{output}",
                parse_mode="HTML"
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Gagal membaca task.md: {e}")

    # ── NineRouter Balance Paging ──
    elif data.startswith("token_page_"):
        page_idx = int(data[len("token_page_"):])
        accounts = NINEROUTER_ACCOUNTS or [
            {
                "account_name": "Akun Antigravity (Personal)",
                "estimated_usd": 185.50,
                "models": [
                    {"model_name": "Claude 3.5 Sonnet", "token_left": 4250000, "token_total": 10000000},
                    {"model_name": "Gemini 1.5 Pro", "token_left": 18400000, "token_total": 20000000},
                    {"model_name": "GPT-4o", "token_left": 800000, "token_total": 2000000}
                ]
            },
            {
                "account_name": "Akun Office (Corporate)",
                "estimated_usd": 94.20,
                "models": [
                    {"model_name": "Claude 3.5 Sonnet", "token_left": 1200000, "token_total": 5000000},
                    {"model_name": "Llama 3 70B", "token_left": 8200000, "token_total": 10000000}
                ]
            },
            {
                "account_name": "Akun Developer (Testing)",
                "estimated_usd": 15.00,
                "models": [
                    {"model_name": "Gemini 1.5 Flash", "token_left": 4500000, "token_total": 5000000}
                ]
            }
        ]
        total_pages = len(accounts)
        text = format_ninerouter_balance_html(accounts[page_idx], page_idx, total_pages)
        buttons = ninerouter_keyboard(page_idx, total_pages)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row]
            for row in buttons
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    # ── Model selection ──
    elif data.startswith("model_"):
        model_key = data[len("model_"):]
        model_idx = -1
        model_name = model_key
        for idx, (name, key) in enumerate(AVAILABLE_MODELS):
            if key == model_key:
                model_idx = idx
                model_name = name
                break
                
        if model_idx != -1:
            await query.answer(f"Changing model to {model_name}...")
            result = ui_controller.switch_model_in_ide(model_idx)
            if result["success"]:
                await query.edit_message_text(
                    f"🤖 <b>Model Switched!</b>\n\n"
                    f"IDE berhasil diubah ke model: <code>{model_name}</code>",
                    parse_mode="HTML",
                    reply_markup=_main_menu_keyboard()
                )
            else:
                await query.edit_message_text(
                    f"❌ <b>Gagal ganti model:</b>\n"
                    f"<code>{result['error']}</code>",
                    parse_mode="HTML",
                    reply_markup=_main_menu_keyboard()
                )

    # ── Session selection ──
    elif data.startswith("sess_"):
        conv_id = data[len("sess_"):]
        ok = _session_manager.set_active_session(conv_id)
        if ok and _transcript_watcher:
            _transcript_watcher.set_transcript(_session_manager.transcript_path)
            title = next((s["title"] for s in _session_manager.get_all_sessions() if s["id"] == conv_id), "")
            await query.edit_message_text(
                f"✅ <b>Switched to session</b>\n\n"
                f"📄 {title}\n"
                f"🔑 <code>{conv_id[:12]}...</code>",
                parse_mode="HTML",
                reply_markup=_main_menu_keyboard()
            )
        else:
            await query.edit_message_text(
                f"❌ Session not found: <code>{conv_id[:12]}...</code>",
                parse_mode="HTML",
                reply_markup=_main_menu_keyboard()
            )

    # ── Action: View Tool Steps ──
    elif data == "action_tool_steps":
        if _last_tool_steps:
            await query.message.reply_text(
                _last_tool_steps,
                parse_mode="HTML"
            )
        else:
            await query.message.reply_text("ℹ️ Tidak ada rincian aktivitas agent saat ini.")

    # ── Action: View Git Diff ──
    elif data == "action_git_diff":
        import subprocess
        from config import PROJECT_DIR
        try:
            res = subprocess.run(["git", "diff"], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=5)
            diff = res.stdout.strip()
            if not diff:
                await query.message.reply_text("ℹ️ Tidak ada perubahan git diff saat ini.")
                return
            
            from transcript_watcher import _esc
            escaped_diff = _esc(diff)
            if len(escaped_diff) > 4000:
                escaped_diff = escaped_diff[:3900] + "\n\n<i>[Diff truncated...]</i>"
                
            await query.message.reply_text(
                f"🔍 <b>Git Diff:</b>\n"
                f"<pre><code class=\"language-diff\">{escaped_diff}</code></pre>",
                parse_mode="HTML"
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Gagal mengambil git diff: {e}")

    # ── Action: Approve (y) ──
    elif data == "action_approve_y":
        await query.answer("Mengirim 'y' ke IDE...")
        result = ui_controller.type_message_to_ide("y")
        if result["success"]:
            await query.message.reply_text("✅ Terkirim ke IDE: <code>y</code>", parse_mode="HTML")
        else:
            await query.message.reply_text(f"❌ Gagal mengirim: {result['error']}")

    # ── Action: Reject (n) ──
    elif data == "action_reject_n":
        await query.answer("Mengirim 'n' ke IDE...")
        result = ui_controller.type_message_to_ide("n")
        if result["success"]:
            await query.message.reply_text("❌ Terkirim ke IDE: <code>n</code>", parse_mode="HTML")
        else:
            await query.message.reply_text(f"❌ Gagal mengirim: {result['error']}")

    # ── Action: Proceed Plan (/approve) ──
    elif data == "action_approve_proceed":
        await query.answer("Mengirim '/approve' ke IDE...")
        result = ui_controller.type_message_to_ide("/approve")
        if result["success"]:
            await query.message.reply_text("🚀 Terkirim ke IDE: <code>/approve</code>", parse_mode="HTML")
        else:
            await query.message.reply_text(f"❌ Gagal mengirim: {result['error']}")

    # ── Action: Option 1 ──
    elif data == "action_option_1":
        await query.answer("Mengirim '1' ke IDE...")
        result = ui_controller.type_message_to_ide("1")
        if result["success"]:
            await query.message.reply_text("✅ Terkirim ke IDE: <code>1</code>", parse_mode="HTML")
        else:
            await query.message.reply_text(f"❌ Gagal mengirim: {result['error']}")

    # ── Action: Option 2 ──
    elif data == "action_option_2":
        await query.answer("Mengirim '2' ke IDE...")
        result = ui_controller.type_message_to_ide("2")
        if result["success"]:
            await query.message.reply_text("✅ Terkirim ke IDE: <code>2</code>", parse_mode="HTML")
        else:
            await query.message.reply_text(f"❌ Gagal mengirim: {result['error']}")

    # ── Action: Option 3 ──
    elif data == "action_option_3":
        await query.answer("Mengirim '3' ke IDE...")
        result = ui_controller.type_message_to_ide("3")
        if result["success"]:
            await query.message.reply_text("✅ Terkirim ke IDE: <code>3</code>", parse_mode="HTML")
        else:
            await query.message.reply_text(f"❌ Gagal mengirim: {result['error']}")




# ─── Message Handler (text → auto-type to IDE) ────────────────────────────────

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    
    msg = update.message.text
    if not msg:
        return
    
    status_msg = await update.message.reply_text("⌨️ Sending to IDE...")
    
    def do_type():
        return ui_controller.type_message_to_ide(msg)
    
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, do_type)
    
    if result["success"]:
        await status_msg.edit_text("✅ Sent to IDE")
    else:
        await status_msg.edit_text(
            f"❌ {result['error']}\n\n"
            "Make sure Antigravity IDE is open."
        )


# ─── Build & Bot Commands ─────────────────────────────────────────────────────

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("coords", cmd_coords))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("task", cmd_task))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("view", cmd_view))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app


async def set_bot_commands(app):
    commands = [
        BotCommand("start", "Start bridge & show menu"),
        BotCommand("menu", "Control panel"),
        BotCommand("status", "Bridge status"),
        BotCommand("coords", "Save mouse position (calibration)"),
        BotCommand("screenshot", "Capture IDE screen"),
        BotCommand("task", "Show todo progress list"),
        BotCommand("run", "Run command in terminal"),
        BotCommand("view", "View specific file content"),
    ]
    await app.bot.set_my_commands(commands)
