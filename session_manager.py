"""
session_manager.py — Kelola active conversation session & list sesi dari brain dir
"""
import os
import json
import glob
from pathlib import Path
from config import ANTIGRAVITY_BRAIN_DIR


class SessionManager:
    def __init__(self):
        self._active_conv_id: str | None = None
        self._transcript_path: str | None = None

    def get_all_sessions(self) -> list[dict]:
        """List semua sesi dari brain dir, sorted by last modified."""
        brain = Path(ANTIGRAVITY_BRAIN_DIR)
        sessions = []
        for conv_dir in brain.iterdir():
            if not conv_dir.is_dir():
                continue
            transcript = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
            if not transcript.exists():
                continue
            # Ambil judul dari conversation — cek baris pertama USER_INPUT
            title = self._extract_title(transcript)
            mtime = transcript.stat().st_mtime
            sessions.append({
                "id": conv_dir.name,
                "title": title,
                "mtime": mtime,
                "transcript_path": str(transcript),
            })
        sessions.sort(key=lambda x: x["mtime"], reverse=True)
        return sessions

    def _extract_title(self, transcript_path: Path) -> str:
        """Ambil preview dari pesan USER_INPUT pertama sebagai judul."""
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                for line in f:
                    obj = json.loads(line)
                    if obj.get("type") == "USER_INPUT":
                        content = obj.get("content", "")
                        # Ambil teks setelah <USER_REQUEST> tag
                        if "<USER_REQUEST>" in content:
                            text = content.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
                            return text[:60] + ("..." if len(text) > 60 else "")
                        return content[:60]
        except Exception:
            pass
        return "Sesi tanpa judul"

    def get_latest_session(self) -> dict | None:
        """Return sesi paling baru."""
        sessions = self.get_all_sessions()
        return sessions[0] if sessions else None

    def set_active_session(self, conv_id: str) -> bool:
        """Set sesi aktif berdasarkan conversation ID."""
        transcript = Path(ANTIGRAVITY_BRAIN_DIR) / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript.exists():
            return False
        self._active_conv_id = conv_id
        self._transcript_path = str(transcript)
        return True

    def auto_detect_active(self) -> bool:
        """Auto set ke sesi paling baru."""
        latest = self.get_latest_session()
        if latest:
            self._active_conv_id = latest["id"]
            self._transcript_path = latest["transcript_path"]
            return True
        return False

    @property
    def active_conv_id(self) -> str | None:
        return self._active_conv_id

    @property
    def transcript_path(self) -> str | None:
        return self._transcript_path
