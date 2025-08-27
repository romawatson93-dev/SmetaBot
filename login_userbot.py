import os
from pyrogram import Client

api_id = os.getenv("TG_API_ID")
api_hash = os.getenv("TG_API_HASH")
session_name = os.getenv("TG_SESSION_NAME", "userbot")
# workdir - локальная папка
workdir = "./sessions"

print(f"Авторизация с API ID: {api_id}")

app = Client(session_name, api_id=int(api_id), api_hash=api_hash, workdir=workdir)

print("Запуск клиента для авторизации...")
app.run()
print("Клиент остановлен. Файл сессии сохранен в ./sessions/")