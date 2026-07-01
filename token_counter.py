"""
token_counter.py — Estimasi token usage dari transcript.jsonl
Menggunakan estimasi kasar: 1 token ≈ 4 karakter
"""
import json
from pathlib import Path


def estimate_tokens(text: str) -> int:
    """Estimasi token dari string (1 token ≈ 4 char)."""
    return max(1, len(text) // 4)


def count_tokens_from_transcript(transcript_path: str) -> dict:
    """
    Baca transcript dan hitung estimasi token.
    Return: { input_tokens, output_tokens, total_tokens, step_count, model }
    """
    input_tokens = 0
    output_tokens = 0
    step_count = 0
    model = "Unknown"

    path = Path(transcript_path)
    if not path.exists():
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "step_count": 0, "model": model}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            step_count += 1
            src = obj.get("source", "")
            typ = obj.get("type", "")
            content = obj.get("content", "")

            if src == "USER_EXPLICIT" and typ == "USER_INPUT":
                input_tokens += estimate_tokens(content)

            elif src == "MODEL" and typ == "PLANNER_RESPONSE":
                output_tokens += estimate_tokens(content)
                # Coba ambil info model dari thinking atau content
                thinking = obj.get("thinking", "")
                output_tokens += estimate_tokens(thinking)

            elif src in ("SYSTEM", "MODEL"):
                # Tool responses count as input context
                input_tokens += estimate_tokens(content)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "step_count": step_count,
        "model": model,
    }


def format_token_message(stats: dict, conv_id: str) -> str:
    """Format token stats jadi pesan Telegram (Markdown)."""
    return (
        f"📊 *Token Usage*\n"
        f"Sesi: `{conv_id[:8]}...`\n\n"
        f"Input:  `~{stats['input_tokens']:,}` tokens\n"
        f"Output: `~{stats['output_tokens']:,}` tokens\n"
        f"Total:  `~{stats['total_tokens']:,}` tokens\n"
        f"Steps:  `{stats['step_count']}`\n"
        f"Model:  `{stats['model']}`"
    )


def format_token_message_html(stats: dict, conv_id: str) -> str:
    """Format token stats for Telegram HTML."""
    return (
        f"📊 <b>Token Usage</b>\n\n"
        f"🔗 Session: <code>{conv_id[:8]}...</code>\n\n"
        f"  Input:   <code>~{stats['input_tokens']:,}</code> tokens\n"
        f"  Output:  <code>~{stats['output_tokens']:,}</code> tokens\n"
        f"  Total:   <code>~{stats['total_tokens']:,}</code> tokens\n"
        f"  Steps:   <code>{stats['step_count']}</code>\n"
        f"  Model:   <code>{stats['model']}</code>"
    )


def format_ninerouter_balance_html(account: dict, page_idx: int, total_pages: int) -> str:
    models_text = []
    for m in account.get("models", []):
        name = m.get("model_name", "Unknown Model")
        left = m.get("token_left", 0)
        total = m.get("token_total", 1)
        pct = (left / total) * 100
        
        bar_length = 10
        filled = int(pct / 10)
        bar = "🟩" * filled + "⬜" * (bar_length - filled)
        
        models_text.append(
            f"• <b>{name}</b>:\n"
            f"  <code>{left:,}</code> / <code>{total:,}</code> ({pct:.1f}%)\n"
            f"  {bar}"
        )
        
    models_section = "\n\n".join(models_text)
    usd = account.get("estimated_usd", 0.0)
    
    return (
        f"🌐 <b>NineRouter Balance Card</b> ({page_idx + 1}/{total_pages})\n\n"
        f"🏷 <b>Nama Akun:</b> <code>{account.get('account_name', 'Unknown')}</code>\n"
        f"💰 <b>Estimasi Total:</b> <code>${usd:.2f}</code>\n\n"
        f"🤖 <b>Models &amp; Tokens:</b>\n\n"
        f"{models_section}"
    )


def ninerouter_keyboard(page_idx: int, total_pages: int) -> list:
    prev_idx = (page_idx - 1) % total_pages
    next_idx = (page_idx + 1) % total_pages
    
    return [
        [
            {"text": "◀ Akun Sebelumnya", "callback_data": f"token_page_{prev_idx}"},
            {"text": "Akun Selanjutnya ▶", "callback_data": f"token_page_{next_idx}"}
        ],
        [
            {"text": "🔄 Refresh Balance", "callback_data": f"token_page_{page_idx}"},
            {"text": "← Back", "callback_data": "menu_back"}
        ]
    ]

