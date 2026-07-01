# Antigravity ↔ Telegram Bridge

## Setup (5 menit)

### 1. Isi `.env`
Copy `.env.example` → `.env`, lalu isi:

```
BOT_TOKEN=7xxxxxxxxx:AAFxxxxx    ← dari @BotFather
CHAT_ID=123456789                ← lihat langkah 2
ALLOWED_USER_IDS=123456789       ← sama dengan CHAT_ID (user ID kamu)
```

**Cara dapat CHAT_ID:**
1. Kirim `/start` ke bot kamu di Telegram
2. Buka browser: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Lihat `result[0].message.chat.id` — itu CHAT_ID kamu

### 2. Jalankan
```powershell
cd C:\Projek\telegram-bridge
python main.py
```

### 3. Kalibrasi input box (wajib untuk auto-type)
1. Buka Antigravity IDE
2. Di Telegram, ketik `/menu` → pilih **🎯 Kalibrasi Input**
3. Hover mouse ke **input box chat** di IDE (kotak tempat ketik pesan)
4. Kirim `/coords` ke bot → koordinat tersimpan

Selesai! Sekarang:
- Ketik pesan di Telegram → otomatis muncul di IDE
- Setiap aksi AI (baca file, run command, dll) → real-time ke Telegram

---

## Fitur

| Fitur | Deskripsi |
|-------|-----------|
| 📖 Baca file | Notif ketika AI baca file |
| 🖊️ Tulis file | Notif ketika AI tulis/edit file |
| 💻 Terminal | Notif ketika AI jalankan command |
| 🤖 AI Response | Respons teks dari AI |
| 🤖 Ganti Model | Pilih model dari menu Telegram |
| 📂 Pilih Sesi | Switch ke sesi percakapan lain |
| 🆕 Sesi Baru | Mulai sesi baru |
| 📊 Token Stats | Lihat estimasi penggunaan token |
| ⏸/▶ Pause/Resume | Pause/resume notifikasi |

## Struktur File
```
telegram-bridge/
├── main.py                # Entry point
├── config.py              # Load .env
├── session_manager.py     # Kelola sesi Antigravity
├── transcript_watcher.py  # Watch & parse transcript.jsonl
├── telegram_handler.py    # Telegram bot logic + inline keyboard
├── ui_controller.py       # PyAutoGUI auto-type
├── token_counter.py       # Estimasi token
├── .env                   # Config (jangan di-commit!)
├── .env.example           # Template
└── requirements.txt
```
