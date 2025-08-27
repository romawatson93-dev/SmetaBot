from pyrogram import Client
import os

api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_name = os.getenv("TG_SESSION_NAME", "userbot")

app = Client(session_name, api_id=api_id, api_hash=api_hash, workdir="/sessions")
print("👉 Введите ТЕЛЕФОН с '+', затем код из Telegram (и 2FA, если есть). НЕ бот-токен.")
app.start()
print(f"✅ Session saved at /sessions/{session_name}.session")
input("Нажмите Enter для выхода...")
app.stop()
