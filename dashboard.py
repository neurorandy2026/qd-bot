"""
Mini dashboard web para controlar el bot desde el browser.
Railway expone el puerto como URL pública.
"""
from aiohttp import web
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

_log: list = []  # últimas 20 entradas del log
_trigger_callback = None  # función para disparar lectura manual


def set_trigger_callback(fn):
    global _trigger_callback
    _trigger_callback = fn


def add_log(msg: str):
    now = datetime.now(ET).strftime("%I:%M:%S %p ET")
    entry = f"[{now}] {msg}"
    _log.append(entry)
    if len(_log) > 20:
        _log.pop(0)
    print(entry)


HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QD Bot — Panel de Control</title>
<style>
  body {{ font-family: monospace; background: #1a1a2e; color: #e0e0e0; padding: 20px; max-width: 700px; margin: 0 auto; }}
  h1 {{ color: #00d4aa; font-size: 1.4em; }}
  .status {{ background: #16213e; padding: 12px; border-radius: 8px; margin: 10px 0; }}
  .status span {{ color: {status_color}; font-weight: bold; }}
  button {{ background: #00d4aa; color: #1a1a2e; border: none; padding: 12px 28px; font-size: 1em;
            font-weight: bold; border-radius: 6px; cursor: pointer; margin: 5px; }}
  button:hover {{ background: #00b894; }}
  button.secondary {{ background: #2d3561; color: #e0e0e0; }}
  .log {{ background: #16213e; padding: 12px; border-radius: 8px; margin-top: 15px; max-height: 350px; overflow-y: auto; }}
  .log-entry {{ border-bottom: 1px solid #2d3561; padding: 5px 0; font-size: 0.88em; color: #a0a0b0; }}
  .log-entry:last-child {{ color: #e0e0e0; }}
</style>
</head>
<body>
<h1>📊 QD Bot — Panel de Control</h1>

<div class="status">
  Estado: <span>{status}</span> &nbsp;·&nbsp; {time_et}
</div>

<div>
  <form method="POST" action="/trigger" style="display:inline">
    <button type="submit">📤 Enviar Lectura Ahora</button>
  </form>
  <form method="POST" action="/trigger?tipo=apertura" style="display:inline">
    <button type="submit" class="secondary">🌅 Apertura</button>
  </form>
  <form method="POST" action="/trigger?tipo=cierre" style="display:inline">
    <button type="submit" class="secondary">🔔 Cierre</button>
  </form>
</div>

<div class="log">
  <strong>Log reciente:</strong><br><br>
  {log_entries}
</div>

<script>setTimeout(() => location.reload(), 30000);</script>
</body>
</html>"""


async def handle_index(request):
    from datetime import datetime
    now = datetime.now(ET)
    time_str = now.strftime("%I:%M:%S %p ET")

    hour = now.hour
    weekday = now.weekday()
    if weekday >= 5 or not (9 <= hour < 16):
        status = "🔴 Mercado Cerrado"
        status_color = "#ff6b6b"
    else:
        status = "🟢 Mercado Abierto"
        status_color = "#00d4aa"

    log_html = "<br>".join(
        f'<div class="log-entry">{e}</div>' for e in reversed(_log)
    ) or '<div class="log-entry">Sin actividad aún</div>'

    html = HTML.format(
        status=status,
        status_color=status_color,
        time_et=time_str,
        log_entries=log_html,
    )
    return web.Response(text=html, content_type="text/html")


async def handle_trigger(request):
    tipo = request.rel_url.query.get("tipo", "lectura")
    if _trigger_callback:
        import asyncio
        asyncio.create_task(_trigger_callback(tipo))
        add_log(f"Lectura manual disparada ({tipo}) desde el panel")
    raise web.HTTPFound("/")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/trigger", handle_trigger)
    return app


async def start_dashboard(port: int = 8080):
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    add_log(f"Dashboard iniciado en puerto {port}")
