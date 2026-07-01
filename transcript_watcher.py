"""
transcript_watcher.py -- Real-time transcript streamer to Telegram
Formats AI activity into professional, visually rich Telegram messages.
Uses HTML parse_mode for reliable formatting.
"""
import json
import time
import threading
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable
from config import PROJECT_DIR

# ─── Emojis ───
EMOJI_DIR = "📁"
EMOJI_READ = "📖"
EMOJI_WRITE = "✏️"
EMOJI_EXECUTE = "💻"
EMOJI_SEARCH = "🔍"
EMOJI_WEB = "🌐"
EMOJI_BROWSER = "🌍"
EMOJI_IMAGE = "🎨"
EMOJI_LOCK = "🔐"
EMOJI_THINK = "💭"
EMOJI_ROBOT = "🤖"
EMOJI_QUESTION = "❓"
EMOJI_TIMER = "⏰"
EMOJI_TASK = "📋"
EMOJI_OTHER = "⚙️"

TOOL_EMOJI = {
    "list_dir": EMOJI_DIR,
    "LIST_DIRECTORY": EMOJI_DIR,
    "read_file": EMOJI_READ,
    "READ_FILE": EMOJI_READ,
    "view_file": EMOJI_READ,
    "VIEW_FILE": EMOJI_READ,
    "write_to_file": EMOJI_WRITE,
    "WRITE_FILE": EMOJI_WRITE,
    "replace_file_content": EMOJI_WRITE,
    "multi_replace_file_content": EMOJI_WRITE,
    "run_command": EMOJI_EXECUTE,
    "RUN_COMMAND": EMOJI_EXECUTE,
    "grep_search": EMOJI_SEARCH,
    "SEARCH_FILES": EMOJI_SEARCH,
    "search_web": EMOJI_WEB,
    "browser_subagent": EMOJI_BROWSER,
    "generate_image": EMOJI_IMAGE,
    "ask_permission": EMOJI_LOCK,
    "ask_question": EMOJI_QUESTION,
    "schedule": EMOJI_TIMER,
    "manage_task": EMOJI_TASK,
    "write_file": EMOJI_WRITE,
    "edit_file": EMOJI_WRITE,
    "create_directory": EMOJI_DIR,
    "move_file": EMOJI_DIR,
}


def _esc(text: str) -> str:
    """Escape HTML special chars for Telegram HTML mode."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _is_valid_url(url: str) -> bool:
    """Check if the URL has a supported Telegram protocol."""
    u = url.strip().lower()
    return any(u.startswith(p) for p in (
        "http://", "https://", "tg://", "file://", "mailto:", "ftp://"
    ))



def markdown_to_html(text: str) -> str:
    """Converts basic Markdown to safe Telegram HTML."""
    # 1. Escape HTML special characters
    text = _esc(text)
    
    # 2. Extract code blocks and replace with placeholders to avoid double formatting
    code_blocks = []
    def save_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2).strip("\r\n")
        placeholder = f"CODEBLOCKXYZ{len(code_blocks)}INDEX"
        if lang:
            formatted = f'<pre><code class="language-{lang}">{code}</code></pre>'
        else:
            formatted = f'<pre><code>{code}</code></pre>'
        code_blocks.append(formatted)
        return placeholder
        
    # Match code blocks with optional language and any newline style (CRLF/LF)
    text = re.sub(r'```([a-zA-Z0-9_-]*)\s*\r?\n(.*?)```', save_code_block, text, flags=re.DOTALL)
    
    # 3. Extract inline code and replace with placeholders
    inline_codes = []
    def save_inline_code(match):
        code = match.group(1)
        placeholder = f"INLINECODEXYZ{len(inline_codes)}INDEX"
        inline_codes.append(f'<code>{code}</code>')
        return placeholder
        
    text = re.sub(r'`([^`\r\n]+)`', save_inline_code, text)

    # 4. Extract markdown links and replace with placeholders (only if protocol is valid)
    links = []
    def save_link(match):
        label = match.group(1)
        url = match.group(2)
        if _is_valid_url(url):
            placeholder = f"LINKPLACEHOLDER{len(links)}INDEX"
            links.append(f'<a href="{url}">{label}</a>')
            return placeholder
        return match.group(0)

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', save_link, text)

    # 5. Convert headers (e.g. ### Header) to bold
    text = re.sub(r'^#{1,6}\s+(.*?)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    
    # 6. Convert bold: **text** -> <b>text</b>
    text = re.sub(r'\*\*([^\*]+)\*\*', r'<b>\1</b>', text)
    
    # 7. Convert italic: *text* -> <i>text</i>
    text = re.sub(r'\*([^\*]+)\*', r'<i>\1</i>', text)
    
    # 8. Convert italic (underscore): _text_ -> <i>text</i>
    text = re.sub(r'_([^_]+)_', r'<i>\1</i>', text)
    
    # 9. Convert bullet points
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("- "):
            lines[i] = line.replace("- ", "• ", 1)
        elif stripped.startswith("* "):
            lines[i] = line.replace("* ", "• ", 1)
    text = "\n".join(lines)
    
    # 10. Restore link placeholders
    for i, formatted in enumerate(links):
        text = text.replace(f"LINKPLACEHOLDER{i}INDEX", formatted)

    # 11. Restore inline codes
    for i, formatted in enumerate(inline_codes):
        text = text.replace(f"INLINECODEXYZ{i}INDEX", formatted)
        
    # 12. Restore code blocks
    for i, formatted in enumerate(code_blocks):
        text = text.replace(f"CODEBLOCKXYZ{i}INDEX", formatted)
        
    return text


def _get_git_changes() -> str:
    """Run git diff --numstat to calculate files changed, insertions, and deletions."""
    try:
        result = subprocess.run(
            ["git", "diff", "--numstat"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=3,
            check=True
        )
        lines = result.stdout.strip().split("\n")
        files_count = 0
        insertions = 0
        deletions = 0
        for line in lines:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 3:
                ins, dels = parts[0], parts[1]
                try:
                    insertions += int(ins)
                    deletions += int(dels)
                    files_count += 1
                except ValueError:
                    files_count += 1 # binary
        
        if files_count == 0:
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
                timeout=3,
                check=True
            )
            untracked = [l for l in status_res.stdout.strip().split("\n") if l.startswith("??")]
            if untracked:
                file_word = "file" if len(untracked) == 1 else "files"
                return f"📄 {len(untracked)} untracked {file_word} ›"
            return ""

        file_word = "file" if files_count == 1 else "files"
        return f"📄 {files_count} {file_word} changed 🟢 +{insertions} 🔴 -{deletions} ›"
    except Exception:
        pass
    return ""


def _get_turn_duration(transcript_path: str, end_time_str: str) -> str:
    """Calculate time difference between start of turn (USER_INPUT) and current step."""
    try:
        end_dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
        last_user_dt = None
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "USER_INPUT":
                        t_str = obj.get("created_at")
                        if t_str:
                            last_user_dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                except Exception:
                    pass
        if last_user_dt:
            diff = (end_dt - last_user_dt).total_seconds()
            return f"{int(diff)}s"
    except Exception:
        pass
    return "0s"


def _short_path(path: str) -> str:
    """Shorten file path for display."""
    if not path or path == "?":
        return "?"
    p = str(path).replace("\\", "/").strip('"').strip("'")
    parts = p.split("/")
    if len(parts) > 3:
        return "/".join(parts[-2:])
    return p


def _format_tool_call(name: str, args: dict) -> str:
    """Format a single tool call into a beautiful layout matching the screenshot."""
    
    if name in ("run_command", "RUN_COMMAND"):
        cmd = str(args.get("CommandLine", args.get("command", "?"))).strip()
        return (
            f"🖥 <b>Ran command</b>\n"
            f"<pre><code class=\"language-powershell\">{_esc(cmd)}</code></pre>"
        )
    
    elif name in ("read_file", "view_file", "read_text_file", "VIEW_FILE", "READ_FILE"):
        path = args.get("AbsolutePath", args.get("path", args.get("Uri", "?")))
        start = args.get("StartLine", "")
        end = args.get("EndLine", "")
        loc = f" (Lines {start}-{end})" if start else ""
        return (
            f"📖 <b>Read file</b>{_esc(loc)}\n"
            f"<pre><code>{_esc(_short_path(path))}</code></pre>"
        )
    
    elif name in ("write_to_file", "WRITE_FILE", "write_file"):
        path = args.get("TargetFile", args.get("path", "?"))
        return (
            f"✏️ <b>Created file</b>\n"
            f"<pre><code>{_esc(_short_path(path))}</code></pre>"
        )

    elif name in ("replace_file_content", "multi_replace_file_content", "edit_file"):
        path = args.get("TargetFile", args.get("path", "?"))
        desc = args.get("Description", "")
        desc_suffix = f" — <i>{_esc(desc)}</i>" if desc else ""
        return (
            f"✏️ <b>Edited file</b>{desc_suffix}\n"
            f"<pre><code>{_esc(_short_path(path))}</code></pre>"
        )
    
    elif name in ("list_dir", "LIST_DIRECTORY"):
        path = args.get("DirectoryPath", args.get("path", "?"))
        return (
            f"📁 <b>List directory</b>\n"
            f"<pre><code>{_esc(_short_path(path))}</code></pre>"
        )
    
    elif name in ("grep_search", "search_files", "SEARCH_FILES"):
        q = args.get("Query", args.get("pattern", "?"))
        path = args.get("SearchPath", args.get("path", ""))
        where = f" in <i>{_esc(_short_path(path))}</i>" if path else ""
        return (
            f"🔍 <b>Search query</b>{where}\n"
            f"<pre><code>{_esc(str(q))}</code></pre>"
        )
    
    elif name == "search_web":
        q = args.get("query", "?")
        return (
            f"🌐 <b>Web search</b>\n"
            f"<pre><code>{_esc(q)}</code></pre>"
        )
    
    elif name == "browser_subagent":
        task = args.get("TaskName", args.get("TaskSummary", "?"))
        return (
            f"🌍 <b>Browser task</b>\n"
            f"<pre><code>{_esc(str(task))}</code></pre>"
        )
    
    elif name == "generate_image":
        prompt = args.get("Prompt", "?")
        return (
            f"🎨 <b>Generate image</b>\n"
            f"<pre><code>{_esc(str(prompt))}</code></pre>"
        )
    
    elif name == "ask_permission":
        target = args.get("Target", "?")
        action = args.get("Action", "?")
        return f"🔐 <b>Minta izin:</b> {_esc(action)} pada <code>{_esc(_short_path(str(target)))}</code>"
    
    elif name == "ask_question":
        return f"❓ <b>Menunggu jawaban user...</b>"
    
    elif name == "schedule":
        return f"⏰ <b>Timer dijadwalkan</b>"
    
    elif name == "manage_task":
        action = args.get("Action", "?")
        return f"📋 <b>Task Manager:</b> {_esc(action)}"
    
    else:
        summary = args.get("toolSummary", args.get("toolAction", name))
        return (
            f"⚙️ <b>Tool call:</b> {name}\n"
            f"<pre><code>{_esc(str(summary))}</code></pre>"
        )


def _format_step(obj: dict, transcript_path: str = None) -> tuple[str | None, str | None, list[str]]:
    """
    Format satu transcript step jadi pesan Telegram profesional (HTML).
    Return ("__RESET__", None, []) if USER_INPUT is detected.
    Return (None, None, []) kalau skip.
    """
    typ = obj.get("type", "")
    source = obj.get("source", "")

    # Reset signal when new user input is detected
    if typ == "USER_INPUT":
        return ("__RESET__", None, [])

    if typ in ("CONVERSATION_HISTORY", "KNOWLEDGE_ARTIFACTS"):
        return (None, None, [])

    # PLANNER_RESPONSE dari MODEL = giliran AI
    if typ == "PLANNER_RESPONSE" and source == "MODEL":
        content = obj.get("content", "").strip()
        thinking = obj.get("thinking", "").strip()
        tool_calls = obj.get("tool_calls", [])
        created_at = obj.get("created_at", "")
        
        compact_sections = []
        actions = []
        
        # ── Worked time (Header) ──
        if created_at and transcript_path:
            duration = _get_turn_duration(transcript_path, created_at)
            compact_sections.append(f"⏱ <b>Worked for {duration} ›</b>")
        
        # ── Thinking (ringkas, italic) ──
        if thinking:
            short = thinking[:150].replace("\n", " ")
            if len(thinking) > 150:
                short += "..."
            # Parse markdown inside thinking preview
            html_thinking = markdown_to_html(short)
            compact_sections.append(f"💭 <i>{html_thinking}</i>")
        
        # ── Tool calls (Detail) ──
        detail_text = None
        if tool_calls:
            detail_sections = ["🛠 <b>Agent Activity</b>"]
            for tc in tool_calls:
                name = tc.get("name", "")
                args = tc.get("args", {})
                detail_sections.append(_format_tool_call(name, args))
            detail_text = "\n\n".join(detail_sections)
            
            # Show tool activity in main bubble ONLY while executing (no final response yet)
            if not content:
                compact_sections.append(detail_text)
            
            # Show remote buttons only when tools are executing (may block for permissions/options)
            actions.extend(["y", "n", "options"])
            
            # Detect plan approval prompts
            content_lower = content.lower()
            if "approve" in content_lower or "feedback" in content_lower or "implementation plan" in content_lower:
                actions.append("proceed")
        
        # ── AI text response ──
        if content:
            if len(content) > 1500:
                content = content[:1500] + "\n..."
            html_content = markdown_to_html(content)
            compact_sections.append(f"🤖 {html_content}")
            
        # ── Git changes (Footer) ──
        git_summary = _get_git_changes()
        if git_summary:
            compact_sections.append(git_summary)
        
        if not compact_sections:
            return (None, None, [])
        
        return ("\n\n".join(compact_sections), detail_text, list(set(actions)))

    return (None, None, [])


class TranscriptWatcher:
    """
    Watch transcript.jsonl real-time.
    """

    def __init__(self, on_new_message: Callable[[str, str | None, list[str]], None]):
        self.on_new_message = on_new_message
        self._transcript_path: str | None = None
        self._last_step_index: int = -1
        self._running = False
        self._thread: threading.Thread | None = None
        self._paused = False

    def set_transcript(self, path: str):
        """Switch transcript yang di-watch."""
        self._transcript_path = path
        self._last_step_index = -1
        self._fast_forward_to_latest()

    def _fast_forward_to_latest(self):
        """Skip existing steps, watch dari step berikutnya."""
        if not self._transcript_path:
            return
        path = Path(self._transcript_path)
        if not path.exists():
            return
        max_idx = -1
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    idx = obj.get("step_index", -1)
                    if idx > max_idx:
                        max_idx = idx
                except Exception:
                    pass
        self._last_step_index = max_idx

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def _watch_loop(self):
        from config import POLLING_INTERVAL
        while self._running:
            if not self._paused and self._transcript_path:
                self._check_new_steps()
            time.sleep(POLLING_INTERVAL)

    def _check_new_steps(self):
        path = Path(self._transcript_path)
        if not path.exists():
            return

        new_steps = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    idx = obj.get("step_index", -1)
                    if idx > self._last_step_index:
                        new_steps.append(obj)

            new_steps.sort(key=lambda x: x.get("step_index", 0))

            for step in new_steps:
                compact, detail, actions = _format_step(step, self._transcript_path)
                self.on_new_message(compact, detail, actions)
                self._last_step_index = max(self._last_step_index, step.get("step_index", 0))

        except Exception as e:
            print(f"[TranscriptWatcher] Error: {e}")
