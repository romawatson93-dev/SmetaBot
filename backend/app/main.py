from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="SmetaBot Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True
)

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/webapp/login", response_class=HTMLResponse)
async def webapp_login():
    return """<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>SmetaBot WebApp Login</title>
  <script src=\"https://telegram.org/js/telegram-web-app.js\"></script>
  <style>
    html,body{height:100%;margin:0;font-family:system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;background:#0f1115;color:#e6e6e6}
    .wrap{min-height:100%;display:flex;align-items:center;justify-content:center;padding:24px}
    .card{background:#151821;border:1px solid #222736;border-radius:12px;max-width:520px;width:100%;padding:24px;box-shadow:0 6px 24px rgba(0,0,0,.35)}
    h1{font-size:18px;margin:0 0 12px}
    p{opacity:.9;margin:0 0 16px}
    button{appearance:none;border:0;border-radius:10px;padding:12px 16px;font-weight:600;background:#3b82f6;color:#fff;cursor:pointer}
    button:active{transform:translateY(1px)}
    code{background:#0b0d12;border:1px solid #1d2230;border-radius:8px;padding:8px 10px;display:block;white-space:pre-wrap}
  </style>
  <script>
    window.addEventListener('DOMContentLoaded', function(){
      const tg = window.Telegram?.WebApp;
      if (tg) { tg.expand(); tg.ready(); }
      const btn = document.getElementById('send');
      btn?.addEventListener('click', function(){
        const payload = {
          action: 'login_test',
          time: Date.now(),
          initData: tg?.initData || null,
          initDataUnsafe: tg?.initDataUnsafe || null
        };
        try { tg?.sendData(JSON.stringify(payload)); } catch(e) { console.error(e); alert('sendData error: '+e.message); }
      });
    });
  </script>
  </head>
<body>
  <div class=\"wrap\">
    <div class=\"card\">
      <h1>Вход через Telegram WebApp</h1>
      <p>Нажмите, чтобы отправить тестовые данные в бота и убедиться, что обработчик получает payload.</p>
      <button id=\"send\">Отправить данные в бота</button>
      <p style=\"margin-top:16px;opacity:.8\">Примерный payload:</p>
      <code>{"action":"login_test","time":<timestamp>,"initData":...,"initDataUnsafe":...}</code>
    </div>
  </div>
</body>
</html>
"""
