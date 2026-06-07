import asyncio
import base64
import uuid
from aiohttp import web
from datetime import datetime, date
from zoneinfo import ZoneInfo
import stats as st
import criteria as cr
import lessons as ls
import claude_client

ET = ZoneInfo("America/New_York")
_log: list = []
_trigger_callback = None
_domingo_callback = None
_anthropic_key: str = ""
_pending_lessons: dict = {}  # temp_id -> pending lesson data
_discord_preview: list = []  # últimos 3 mensajes enviados a Discord
_last_ask: dict = {}         # última consulta al bot desde el dashboard

RULES_PASSWORD = "1611"


def set_trigger_callback(fn):
    global _trigger_callback
    _trigger_callback = fn


def set_domingo_callback(fn):
    global _domingo_callback
    _domingo_callback = fn


def set_anthropic_key(key: str):
    global _anthropic_key
    _anthropic_key = key


def add_log(msg: str):
    now = datetime.now(ET).strftime("%I:%M:%S %p")
    entry = f"{now} — {msg}"
    _log.append(entry)
    if len(_log) > 30:
        _log.pop(0)
    print(f"[Dashboard] {entry}")


def add_discord_preview(text: str, tipo: str, label: str = ""):
    """Guarda el mensaje enviado a Discord para mostrarlo en el panel de preview."""
    global _discord_preview
    now = datetime.now(ET).strftime("%I:%M %p ET")
    _discord_preview.insert(0, {"text": text, "tipo": tipo.upper(), "label": label, "time": now})
    if len(_discord_preview) > 3:
        _discord_preview.pop()


HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QD Bot</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; min-height: 100vh; padding: 20px; }}
  h1 {{ font-size: 1.35em; color: #58a6ff; margin-bottom: 4px; font-weight: 700; letter-spacing: -0.3px; }}
  .subtitle {{ color: #8b949e; font-size: 0.82em; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 12px; margin-bottom: 20px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-top: 2px solid #21262d; border-radius: 10px; padding: 14px; transition: border-top-color 0.3s; }}
  .card:hover {{ border-top-color: #58a6ff; }}
  .card .label {{ color: #8b949e; font-size: 0.71em; text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 8px; font-weight: 700; }}
  .card .value {{ font-size: 1.9em; font-weight: 700; color: #f0f6fc; line-height: 1; }}
  .card .value.green {{ color: #3fb950; }}
  .card .value.yellow {{ color: #d29922; }}
  .card .value.blue {{ color: #58a6ff; }}
  .card .value.red {{ color: #f85149; }}
  .card .sub {{ color: #8b949e; font-size: 0.75em; margin-top: 7px; }}
  .status-bar {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 12px 16px;
                 display: flex; align-items: center; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; flex-shrink: 0; }}
  .dot.green {{ background: #3fb950; box-shadow: 0 0 7px #3fb950; }}
  .dot.red {{ background: #f85149; }}
  .dot.yellow {{ background: #d29922; box-shadow: 0 0 7px #d29922; animation: pulse 1.5s infinite; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.5}} }}
  .btn-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }}
  button {{ border: none; padding: 10px 18px; font-size: 0.88em; font-weight: 600;
            border-radius: 8px; cursor: pointer; transition: opacity 0.15s, transform 0.1s;
            min-height: 42px; line-height: 1.2; font-family: inherit; }}
  button:hover {{ opacity: 0.82; }}
  button:active {{ transform: scale(0.97); opacity: 1; }}
  .btn-primary {{ background: #238636; color: #fff; }}
  .btn-secondary {{ background: #1f6feb; color: #fff; }}
  .btn-ghost {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
  .btn-danger {{ background: #6e1c1c; color: #f85149; border: 1px solid #6e1c1c; font-size: 0.78em; padding: 6px 12px; min-height: 36px; }}
  .btn-purple {{ background: #4a1d96; color: #c4b5fd; border: 1px solid #6d28d9; }}
  .btn-teal {{ background: #0e4429; color: #56d364; border: 1px solid #238636; }}
  .btn-sm {{ padding: 4px 12px; font-size: 0.78em; min-height: 30px; }}
  .panels {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  @media(max-width: 640px) {{ .panels {{ grid-template-columns: 1fr; }} }}
  .panel {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px; }}
  .panel h3 {{ color: #8b949e; font-size: 0.71em; text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 12px; font-weight: 700; }}
  .log-entry {{ font-size: 0.75em; padding: 5px 0; border-bottom: 1px solid #21262d; color: #8b949e; font-family: 'Courier New', monospace; }}
  .log-entry:first-child {{ color: #c9d1d9; }}
  .log-entry:last-child {{ border-bottom: none; }}
  .level-chip {{ display: inline-block; background: #21262d; border-radius: 4px; padding: 3px 9px;
                 font-size: 0.82em; margin: 2px; border: 1px solid #30363d; font-weight: 600; }}
  .level-chip.support {{ border-color: #3fb950; color: #3fb950; }}
  .level-chip.resistance {{ border-color: #f85149; color: #f85149; }}
  .history-row {{ display: flex; justify-content: space-between; align-items: center; font-size: 0.8em; padding: 5px 0;
                  border-bottom: 1px solid #21262d; gap: 6px; }}
  .history-row:last-child {{ border-bottom: none; }}
  .badge {{ padding: 2px 9px; border-radius: 10px; font-size: 0.75em; font-weight: 700; white-space: nowrap; }}
  .badge.green {{ background: #0d4429; color: #3fb950; }}
  .badge.red {{ background: #3d0f0f; color: #f85149; }}
  .accuracy-bar {{ background: #21262d; border-radius: 4px; height: 6px; margin-top: 8px; overflow: hidden; }}
  .accuracy-fill {{ height: 100%; background: linear-gradient(90deg, #2ea043, #56d364); border-radius: 4px; transition: width 0.6s ease; }}
  .discord-msg {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 10px 12px;
                  margin-bottom: 8px; font-size: 0.76em; white-space: pre-wrap; line-height: 1.55; font-family: 'Courier New', monospace; }}
  .discord-msg .msg-header {{ color: #8b949e; font-size: 0.85em; margin-bottom: 6px; font-family: inherit; }}
  .preview-panel {{ background: #0c1929; border: 1px solid #1f4070; border-radius: 10px; padding: 14px; margin-bottom: 12px; }}
  .preview-panel h3 {{ color: #58a6ff; font-size: 0.71em; text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 12px; font-weight: 700; }}
  .preview-msg {{ background: #0d1117; border-left: 3px solid #1f6feb; border-radius: 0 8px 8px 0; padding: 10px 14px;
                  margin-bottom: 10px; font-size: 0.8em; white-space: pre-wrap; line-height: 1.65; color: #c9d1d9; font-family: 'Courier New', monospace; }}
  .preview-msg .msg-meta {{ color: #58a6ff; font-size: 0.75em; margin-bottom: 7px; font-weight: 700; font-family: inherit; text-transform: uppercase; letter-spacing: 0.8px; }}
  .preview-empty {{ color: #8b949e; font-size: 0.82em; text-align: center; padding: 24px; }}
  .pwd-input {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px; color: #c9d1d9;
                padding: 9px 12px; font-size: 0.88em; width: 110px; min-height: 42px; font-family: inherit; }}
  .pwd-input:focus {{ outline: none; border-color: #58a6ff; box-shadow: 0 0 0 3px rgba(88,166,255,0.12); }}
  /* Criteria styles */
  .criteria-form {{ display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }}
  .criteria-form input[type=text] {{ flex: 1; min-width: 200px; background: #0d1117; border: 1px solid #30363d;
    border-radius: 8px; color: #c9d1d9; padding: 9px 12px; font-size: 0.85em; min-height: 42px; font-family: inherit; }}
  .criteria-form input[type=text]:focus {{ outline: none; border-color: #58a6ff; box-shadow: 0 0 0 3px rgba(88,166,255,0.12); }}
  .criteria-form select {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
    color: #c9d1d9; padding: 9px 10px; font-size: 0.85em; min-height: 42px; font-family: inherit; }}
  .rule-card {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 10px 12px;
                margin-bottom: 8px; }}
  .rule-card.inactive {{ opacity: 0.4; }}
  .rule-header {{ display: flex; align-items: flex-start; gap: 8px; margin-bottom: 4px; }}
  .rule-text {{ font-size: 0.85em; color: #c9d1d9; flex: 1; line-height: 1.4; }}
  .cat-badge {{ font-size: 0.7em; padding: 2px 7px; border-radius: 10px; font-weight: 600; white-space: nowrap; flex-shrink: 0; }}
  .cat-DEX {{ background: #0d2137; color: #58a6ff; }}
  .cat-GEX {{ background: #0d2b1a; color: #3fb950; }}
  .cat-Mensajes {{ background: #2b1f0d; color: #d29922; }}
  .cat-Alertas {{ background: #2b0d1a; color: #f85149; }}
  .cat-General {{ background: #21262d; color: #8b949e; }}
  .rule-meta {{ font-size: 0.72em; color: #8b949e; margin-top: 3px; }}
  .toggle {{ cursor: pointer; font-size: 1.1em; }}
  .active-prompt-preview {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    padding: 8px 12px; font-size: 0.73em; color: #8b949e; white-space: pre-wrap;
    max-height: 80px; overflow-y: auto; margin-bottom: 10px; font-family: 'Courier New', monospace; }}
  /* Lessons styles */
  .lesson-form {{ display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }}
  .lesson-form textarea {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
    color: #c9d1d9; padding: 8px 12px; font-size: 0.85em; resize: vertical; min-height: 70px;
    font-family: inherit; }}
  .lesson-form textarea:focus {{ outline: none; border-color: #58a6ff; }}
  .lesson-form-row {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .lesson-form select {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
    color: #c9d1d9; padding: 8px; font-size: 0.85em; }}
  .paste-zone {{ border: 2px dashed #30363d; border-radius: 8px; padding: 14px 16px;
    text-align: center; color: #8b949e; font-size: 0.82em; cursor: pointer;
    transition: border-color 0.2s, background 0.2s; background: #0d1117; position: relative; }}
  .paste-zone:focus {{ outline: none; }}
  .paste-zone.has-image {{ border-color: #238636; background: #0d2119; }}
  .paste-zone.active {{ border-color: #58a6ff; background: #0d1a2e; }}
  .paste-preview {{ max-width: 100%; max-height: 200px; border-radius: 6px; margin-top: 8px;
    border: 1px solid #30363d; display: block; }}
  .paste-clear {{ position: absolute; top: 6px; right: 8px; background: #6e1c1c;
    color: #f85149; border: none; border-radius: 4px; padding: 2px 8px; font-size: 0.75em;
    cursor: pointer; display: none; min-height: unset; }}
  .lesson-card {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
    padding: 10px 12px; margin-bottom: 8px; display: flex; gap: 10px; }}
  .lesson-card.inactive {{ opacity: 0.4; }}
  .lesson-thumb {{ width: 64px; height: 48px; object-fit: cover; border-radius: 4px;
    border: 1px solid #30363d; flex-shrink: 0; background: #21262d; }}
  .lesson-thumb-empty {{ width: 64px; height: 48px; border-radius: 4px; border: 1px dashed #30363d;
    flex-shrink: 0; display: flex; align-items: center; justify-content: center;
    font-size: 1.2em; color: #30363d; }}
  .lesson-body {{ flex: 1; min-width: 0; }}
  .lesson-rule {{ font-size: 0.83em; color: #c9d1d9; line-height: 1.4; margin-bottom: 3px; }}
  .lesson-meta {{ font-size: 0.72em; color: #8b949e; }}
  .lesson-actions {{ display: flex; flex-direction: column; gap: 4px; align-items: flex-end; flex-shrink: 0; }}
  .lesson-count {{ font-size: 0.75em; color: #8b949e; margin-bottom: 10px; }}
  .cat-Formato {{ background: #1a1a2e; color: #8b8bff; }}
  .cat-Error {{ background: #2b0d1a; color: #f85149; }}
  .cat-Ejemplo {{ background: #0d2b1a; color: #3fb950; }}
  .cat-Criterio {{ background: #2b1a0d; color: #d29922; }}
  /* ── Log panel terminal ── */
  .log-panel {{ background: #080d11; border-color: #1a3326; border-left: 3px solid #2ea043; }}
  .log-panel h3 {{ color: #56d364; }}
  .log-panel .log-entry {{ color: #6e8070; border-bottom-color: #101a14; }}
  .log-panel .log-entry:first-child {{ color: #56d364; font-weight: 600; }}
  .live-badge {{ display: inline-block; font-size: 0.9em; color: #3fb950;
    font-weight: 700; animation: pulse 2s infinite; margin-left: 8px;
    text-transform: none; letter-spacing: 0.3px; }}
  /* ── Tooltips ── */
  .btn-wrap {{ display: flex; align-items: center; gap: 5px; }}
  .tip {{ display: inline-flex; align-items: center; justify-content: center;
    width: 17px; height: 17px; border-radius: 50%; background: #1c2128;
    border: 1px solid #30363d; color: #8b949e; font-size: 0.68em; font-weight: 700;
    cursor: help; position: relative; vertical-align: middle; flex-shrink: 0;
    line-height: 1; user-select: none; }}
  .tip::after {{ content: attr(data-tip); position: absolute; bottom: calc(100% + 9px);
    left: 50%; transform: translateX(-50%); background: #1c2128; border: 1px solid #444c56;
    color: #c9d1d9; font-size: 1.5em; font-weight: 400; padding: 8px 11px;
    border-radius: 8px; width: 210px; opacity: 0; pointer-events: none;
    transition: opacity 0.15s; z-index: 200; line-height: 1.45;
    box-shadow: 0 6px 20px rgba(0,0,0,0.5); text-align: left; white-space: normal; }}
  .tip:hover::after, .tip.open::after {{ opacity: 1; }}
  .section-tip {{ margin-left: 6px; }}
  /* ── Mobile ── */
  @media(max-width: 520px) {{
    body {{ padding: 12px; }}
    h1 {{ font-size: 1.15em; }}
    .btn-row {{ gap: 8px; }}
    .btn-row form {{ flex: 1; min-width: calc(50% - 4px); }}
    .btn-row button {{ width: 100%; justify-content: center; }}
    button {{ min-height: 48px; }}
    .btn-sm {{ min-height: 32px; }}
    .criteria-form {{ flex-direction: column; }}
    .criteria-form input[type=text],
    .criteria-form select,
    .pwd-input {{ width: 100%; min-width: unset; }}
    .criteria-form button.btn-primary.btn-sm {{ width: 100%; padding: 12px; font-size: 0.9em; min-height: 46px; }}
    .status-bar {{ gap: 8px; font-size: 0.88em; padding: 10px 12px; }}
    .grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>

<h1>📊 QD Bot — Panel de Control</h1>
<p class="subtitle">Lector de mercado en tiempo real · Actualiza cada 5s</p>

<div class="status-bar">
  <span class="dot {dot_class}"></span>
  <strong>{market_status}</strong>
  <span style="color:#8b949e">·</span>
  <span style="color:#8b949e">{time_et}</span>
  <span style="color:#8b949e">·</span>
  <span>{last_ticker} <strong style="color:#58a6ff">${last_price}</strong></span>
  <span style="color:#8b949e;font-size:0.8em">Último msg: {last_msg_time}</span>
  <span style="margin-left:auto;background:#0a1f12;border:1px solid #2ea043;border-radius:20px;
               padding:4px 12px;font-size:0.8em;font-weight:700;color:#3fb950;
               letter-spacing:0.5px;animation:pulse 2s infinite;white-space:nowrap">● LIVE</span>
</div>

<div class="grid">
  <div class="card">
    <div class="label">Lecturas Hoy</div>
    <div class="value blue">{today_lecturas}</div>
    <div class="sub">Total: {total_lecturas}</div>
  </div>
  <div class="card">
    <div class="label">Alertas Hoy</div>
    <div class="value yellow">{today_alertas}</div>
    <div class="sub">Total: {total_alertas}</div>
  </div>
  <div class="card">
    <div class="label">Precisión</div>
    <div class="value {accuracy_color}">{accuracy}%</div>
    <div class="accuracy-bar"><div class="accuracy-fill" style="width:{accuracy}%"></div></div>
    <div class="sub">{levels_held}✅ {levels_broken}❌</div>
  </div>
  <div class="card">
    <div class="label">Reglas Activas</div>
    <div class="value green">{active_rules}</div>
    <div class="sub">de {total_rules} reglas</div>
  </div>
  <div class="card">
    <div class="label">Lecciones Activas</div>
    <div class="value blue">{active_lessons}</div>
    <div class="sub">de {total_lessons} lecciones</div>
  </div>
</div>

<div class="btn-row">
  <div class="btn-wrap">
    <form method="POST" action="/trigger" style="display:inline">
      <button type="submit" class="btn-primary">📤 Enviar Lectura Ahora</button>
    </form>
    <span class="tip" data-tip="Envía una lectura del SPX a Discord en este momento, sin esperar el ciclo automático de 20 min.">?</span>
  </div>
  <div class="btn-wrap">
    <form method="POST" action="/trigger?tipo=apertura" style="display:inline">
      <button type="submit" class="btn-secondary">🌅 Apertura</button>
    </form>
    <span class="tip" data-tip="Genera el mensaje especial de apertura con los niveles clave del día y contexto de flujo.">?</span>
  </div>
  <div class="btn-wrap">
    <form method="POST" action="/trigger?tipo=cierre" style="display:inline">
      <button type="submit" class="btn-ghost">🔔 Cierre</button>
    </form>
    <span class="tip" data-tip="Genera el resumen de cierre: qué niveles aguantaron, qué rompió y qué vigilar mañana.">?</span>
  </div>
  <div class="btn-wrap">
    <form method="POST" action="/domingo" style="display:inline">
      <button type="submit" class="btn-purple">📅 Analisis Dominical SPX</button>
    </form>
    <span class="tip" data-tip="Produce el análisis semanal completo del SPX. Se envía automáticamente cada domingo, pero puedes forzarlo aquí.">?</span>
  </div>
  <div class="btn-wrap">
    <form method="POST" action="/darkpool-status" style="display:inline">
      <button type="submit" class="btn-teal">🏦 Estado Dark Pool</button>
    </form>
    <span class="tip" data-tip="Consulta el scanner institucional y envía al canal de dark pool qué empresas están acumulando flujo en este momento.">?</span>
  </div>
  <div class="btn-wrap">
    <form method="POST" action="/reset-accuracy" style="display:inline" onsubmit="return confirm('¿Resetear contadores de precisión?')">
      <button type="submit" class="btn-danger" style="font-size:0.78em;padding:6px 12px">🔄 Reset Precisión</button>
    </form>
    <span class="tip" data-tip="Reinicia los contadores de niveles aguantados y rotos. Útil al inicio de una nueva semana.">?</span>
  </div>
</div>

<div class="panel log-panel" style="margin-bottom:12px">
  <h3>📋 Log del Bot <span class="live-badge">● LIVE</span>
    <span class="tip section-tip" data-tip="Registro en tiempo real de toda la actividad del bot: lecturas, alertas, errores y acciones manuales. Se actualiza cada 5 seg.">?</span>
  </h3>
  {log_html}
</div>

<div class="preview-panel">
  <h3>📱 Vista Previa Discord — últimos mensajes del bot
    <span class="tip section-tip" data-tip="Muestra los últimos 3 mensajes que el bot envió a Discord. Verifica aquí qué recibieron tus coaches antes de que llegue al canal.">?</span>
  </h3>
  {preview_html}
</div>

<div class="panel" style="margin-bottom:12px;background:#0c1117;border-color:#1f3a5f;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
  <div>
    <h3 style="color:#7cb9ff;margin-bottom:4px">🤖 Consulta a Randy
      <span class="tip section-tip" data-tip="Hazle una pregunta directa al bot con los datos actuales del mercado. Se abre en una página sin auto-refresh para que puedas escribir con calma.">?</span>
    </h3>
    <p style="color:#8b949e;font-size:0.8em">Pregunta libre · El bot responde con datos en tiempo real</p>
  </div>
  <a href="/ask" target="_blank"><button class="btn-secondary">Abrir Consulta →</button></a>
</div>

<div class="panels">
  <div class="panel">
    <h3>📍 Niveles Activos
      <span class="tip section-tip" data-tip="Soportes y resistencias que el bot monitorea en tiempo real. Si el precio se acerca, el bot evalúa si aguanta o rompe.">?</span>
    </h3>
    {active_levels_html}
  </div>
  <div class="panel">
    <h3>🎯 Historial de Niveles
      <span class="tip section-tip" data-tip="Registro de cada nivel probado: ✅ si el precio aguantó la zona, ❌ si la rompió. Usado para calcular la precisión.">?</span>
    </h3>
    {history_html}
  </div>
</div>

<div class="panel" style="margin-top:12px">
  <h3>🧠 Criterio del Instructor — Reglas Activas en Claude
    <span class="tip section-tip" data-tip="Reglas que Randy agrega para afinar cómo Claude interpreta el mercado. Requiere clave 🔑. Solo el instructor puede modificarlas.">?</span>
  </h3>

  <form class="criteria-form" method="POST" action="/add-rule">
    <input type="text" name="rule_text" placeholder="Nueva regla... ej: Si hay zona magnética de 3 strikes, mencionar el target exacto" required>
    <select name="category">
      <option value="General">General</option>
      <option value="DEX">DEX</option>
      <option value="GEX">GEX</option>
      <option value="Mensajes">Mensajes</option>
      <option value="Alertas">Alertas</option>
    </select>
    <input type="password" name="password" placeholder="🔑 Clave" class="pwd-input" required>
    <button type="submit" class="btn-primary btn-sm">+ Agregar</button>
  </form>

  {rules_html}

  {prompt_preview_html}
</div>

<div class="panel" style="margin-top:12px">
  <h3>💬 Últimos Mensajes a Discord
    <span class="tip section-tip" data-tip="Copia de los últimos 2 mensajes enviados al canal principal de Discord con marca de tiempo.">?</span>
  </h3>
  {discord_msgs_html}
</div>

<div class="panel" style="margin-top:12px">
  <h3>🏦 Historial Dark Pool Institucional
    <span class="tip section-tip" data-tip="Alertas de flujo institucional detectadas: empresas donde entraron +$20M en dark pool en la misma dirección en menos de 10 min.">?</span>
  </h3>
  {darkpool_history_html}
</div>

<div class="panel" style="margin-top:12px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
  <div>
    <h3 style="margin-bottom:4px">📚 Lecciones de Aprendizaje
      <span class="tip section-tip" data-tip="Banco de aprendizaje donde Randy enseña al bot con observaciones e imágenes. Las lecciones activas se inyectan en cada lectura de Claude.">?</span>
    </h3>
    <p style="color:#8b949e;font-size:0.8em">{active_lessons} activas inyectadas en cada lectura de Claude</p>
  </div>
  <a href="/lessons"><button class="btn-secondary">Abrir Lecciones →</button></a>
</div>

<script>
// Auto-refresh cada 5s — NUNCA se detiene
setTimeout(() => location.reload(), 5000);

// Preserva el texto del input de consulta a través del reload
(function() {{
  const KEY = 'qd_ask_draft';
  const inp = document.getElementById('ask-input');
  if (!inp) return;
  const saved = sessionStorage.getItem(KEY);
  if (saved) {{ inp.value = saved; sessionStorage.removeItem(KEY); }}
  inp.addEventListener('input', () => sessionStorage.setItem(KEY, inp.value));
  inp.closest('form').addEventListener('submit', () => sessionStorage.removeItem(KEY));
}})();

// Mobile: tap ? para tooltip
document.addEventListener('click', function(e) {{
  const tip = e.target.closest('.tip');
  if (!tip) {{ document.querySelectorAll('.tip.open').forEach(t => t.classList.remove('open')); return; }}
  const wasOpen = tip.classList.contains('open');
  document.querySelectorAll('.tip.open').forEach(t => t.classList.remove('open'));
  if (!wasOpen) tip.classList.add('open');
  e.stopPropagation();
}});
</script>
</body>
</html>"""


QUESTIONS_LOG_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preguntas al Bot</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9;
          min-height: 100vh; padding: 24px 20px; max-width: 800px; margin: 0 auto; }}
  h1 {{ font-size: 1.3em; color: #58a6ff; margin-bottom: 4px; font-weight: 700; }}
  .subtitle {{ color: #8b949e; font-size: 0.82em; margin-bottom: 24px; }}
  .back-link {{ display: inline-block; color: #8b949e; font-size: 0.82em;
                margin-bottom: 18px; text-decoration: none; }}
  .back-link:hover {{ color: #58a6ff; }}
  .auth-box {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px;
               padding: 28px; max-width: 340px; margin: 60px auto; text-align: center; }}
  .auth-box h2 {{ color: #58a6ff; font-size: 1.1em; margin-bottom: 16px; }}
  .auth-box input {{ width: 100%; background: #0d1117; border: 1px solid #30363d;
    border-radius: 8px; color: #c9d1d9; padding: 11px 14px; font-size: 1em;
    font-family: inherit; text-align: center; letter-spacing: 4px; margin-bottom: 12px; outline: none; }}
  .auth-box input:focus {{ border-color: #58a6ff; }}
  .auth-box button {{ width: 100%; background: #1f6feb; color: #fff; border: none;
    padding: 11px; border-radius: 8px; font-size: 0.92em; font-weight: 700;
    cursor: pointer; font-family: inherit; }}
  .error {{ color: #f85149; font-size: 0.82em; margin-top: 8px; }}
  .stats-bar {{ display: flex; gap: 20px; background: #161b22; border: 1px solid #30363d;
                border-radius: 10px; padding: 14px 18px; margin-bottom: 20px; flex-wrap: wrap; }}
  .stat {{ text-align: center; }}
  .stat .n {{ font-size: 1.6em; font-weight: 700; color: #58a6ff; }}
  .stat .l {{ font-size: 0.72em; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }}
  .q-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px;
              padding: 14px 16px; margin-bottom: 10px; }}
  .q-meta {{ font-size: 0.72em; color: #8b949e; margin-bottom: 8px; }}
  .q-text {{ font-size: 0.9em; color: #f0f6fc; font-weight: 600; margin-bottom: 8px; }}
  .q-answer {{ font-size: 0.83em; color: #8b949e; line-height: 1.55;
               border-left: 2px solid #30363d; padding-left: 10px; }}
  .filter-row {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }}
  .filter-row input {{ flex: 1; min-width: 160px; background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; color: #c9d1d9; padding: 8px 12px; font-size: 0.85em; font-family: inherit; outline: none; }}
  .filter-row input:focus {{ border-color: #58a6ff; }}
  .count {{ color: #8b949e; font-size: 0.82em; }}
  .empty {{ color: #8b949e; text-align: center; padding: 40px; font-size: 0.9em; }}
</style>
</head>
<body>
<a class="back-link" href="/">← Dashboard</a>
<h1>🔍 Preguntas al Bot</h1>
<p class="subtitle">Solo visible para Randy · {total} preguntas registradas</p>

{content}

<script>
function filterQ() {{
  const q = document.getElementById('search').value.toLowerCase();
  document.querySelectorAll('.q-card').forEach(card => {{
    card.style.display = card.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""


ASK_PAGE_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Consulta a Randy</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
          background: #0d1117; color: #c9d1d9; min-height: 100vh;
          padding: 24px 20px; max-width: 720px; margin: 0 auto; }}
  h1 {{ font-size: 1.35em; color: #58a6ff; margin-bottom: 4px; font-weight: 700; }}
  .subtitle {{ color: #8b949e; font-size: 0.84em; margin-bottom: 24px; }}
  .back-link {{ display: inline-block; color: #8b949e; font-size: 0.82em;
                margin-bottom: 18px; text-decoration: none; }}
  .back-link:hover {{ color: #58a6ff; }}
  .ask-form {{ display: flex; flex-direction: column; gap: 10px; margin-bottom: 24px; }}
  .ask-form input[type=text] {{ width: 100%; background: #161b22; border: 1px solid #30363d;
    border-radius: 10px; color: #f0f6fc; padding: 14px 16px; font-size: 1em;
    font-family: inherit; outline: none; transition: border-color 0.2s; }}
  .ask-form input[type=text]:focus {{ border-color: #58a6ff;
    box-shadow: 0 0 0 3px rgba(88,166,255,0.12); }}
  .ask-form input[type=text]::placeholder {{ color: #484f58; }}
  button {{ border: none; padding: 13px 24px; font-size: 0.92em; font-weight: 700;
            border-radius: 10px; cursor: pointer; font-family: inherit;
            transition: opacity 0.15s, transform 0.1s; }}
  button:hover {{ opacity: 0.85; }}
  button:active {{ transform: scale(0.97); }}
  .btn-primary {{ background: #1f6feb; color: #fff; width: 100%; }}
  .btn-ghost {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 8px 16px; font-size: 0.85em; }}
  .answer-box {{ background: #0c1929; border: 1px solid #1f4070; border-radius: 12px;
                 padding: 20px 22px; margin-bottom: 20px; }}
  .answer-meta {{ color: #58a6ff; font-size: 0.72em; font-weight: 700; text-transform: uppercase;
                  letter-spacing: 1px; margin-bottom: 10px; }}
  .answer-question {{ color: #8b949e; font-size: 0.85em; font-style: italic;
                      margin-bottom: 14px; padding-bottom: 12px;
                      border-bottom: 1px solid #1f3a5f; }}
  .answer-text {{ font-size: 0.97em; line-height: 1.75; color: #e6edf3; }}
  .examples {{ margin-top: 20px; }}
  .examples h3 {{ color: #8b949e; font-size: 0.72em; text-transform: uppercase;
                  letter-spacing: 1px; margin-bottom: 10px; font-weight: 700; }}
  .example-btn {{ display: block; width: 100%; text-align: left; background: #161b22;
                  border: 1px solid #30363d; border-radius: 8px; color: #8b949e;
                  padding: 10px 14px; font-size: 0.84em; margin-bottom: 6px;
                  cursor: pointer; font-family: inherit; transition: border-color 0.2s, color 0.2s; }}
  .example-btn:hover {{ border-color: #58a6ff; color: #c9d1d9; }}
  .loading {{ display: none; color: #58a6ff; font-size: 0.85em; text-align: center; padding: 20px; }}
</style>
</head>
<body>

<a class="back-link" href="/">← Volver al Dashboard</a>
<h1>🤖 Consulta a Randy</h1>
<p class="subtitle">Pregunta directa · El bot consulta los datos actuales del mercado</p>

{answer_section}

<form class="ask-form" method="POST" action="/ask" id="ask-form">
  <input type="text" name="question" id="ask-input"
         placeholder="ej: ¿Hasta dónde podría llegar el SPX al alza hoy?"
         value="{prefill}" autocomplete="off" autofocus>
  <button type="submit" class="btn-primary" id="ask-btn">Consultar →</button>
</form>

<div class="examples">
  <h3>Ideas de preguntas</h3>
  <button class="example-btn" onclick="setQ(this)">¿Dónde está el MVC hoy?</button>
  <button class="example-btn" onclick="setQ(this)">¿Hasta dónde podría llegar el SPX al alza hoy?</button>
  <button class="example-btn" onclick="setQ(this)">¿Qué nivel es el más importante ahora mismo?</button>
  <button class="example-btn" onclick="setQ(this)">¿Es buen momento para vender primas?</button>
  <button class="example-btn" onclick="setQ(this)">¿Qué pasa si el SPX pierde el pivote?</button>
</div>

<script>
function setQ(btn) {{
  document.getElementById('ask-input').value = btn.textContent;
  document.getElementById('ask-input').focus();
}}
document.getElementById('ask-form').addEventListener('submit', function() {{
  document.getElementById('ask-btn').textContent = 'Consultando...';
  document.getElementById('ask-btn').disabled = true;
}});
</script>
</body>
</html>"""


LESSONS_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QD Bot — Lecciones</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', monospace; background: #0d1117; color: #c9d1d9; min-height: 100vh; padding: 20px; max-width: 800px; margin: 0 auto; }}
  h1 {{ font-size: 1.3em; color: #58a6ff; margin-bottom: 4px; }}
  .subtitle {{ color: #8b949e; font-size: 0.82em; margin-bottom: 20px; }}
  .panel {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 16px; margin-bottom: 14px; }}
  .panel h3 {{ color: #8b949e; font-size: 0.78em; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }}
  .back-link {{ display: inline-block; color: #8b949e; font-size: 0.82em; margin-bottom: 16px; text-decoration: none; }}
  .back-link:hover {{ color: #58a6ff; }}
  /* Form */
  .lesson-form {{ display: flex; flex-direction: column; gap: 10px; }}
  .lesson-form textarea {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    color: #c9d1d9; padding: 10px 12px; font-size: 0.88em; resize: vertical; min-height: 80px; font-family: inherit; }}
  .lesson-form textarea:focus {{ outline: none; border-color: #58a6ff; }}
  .form-row {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .form-row select {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    color: #c9d1d9; padding: 8px; font-size: 0.85em; }}
  /* Paste zone */
  .paste-zone {{ border: 2px dashed #30363d; border-radius: 8px; padding: 18px;
    text-align: center; color: #8b949e; font-size: 0.85em; cursor: pointer;
    transition: border-color 0.2s, background 0.2s; background: #0d1117; position: relative; }}
  .paste-zone:focus {{ outline: none; }}
  .paste-zone.has-image {{ border-color: #238636; background: #0d2119; }}
  .paste-zone.active {{ border-color: #58a6ff; background: #0d1a2e; }}
  .paste-preview {{ max-width: 100%; max-height: 260px; border-radius: 6px; margin-top: 10px;
    border: 1px solid #30363d; display: block; margin-left: auto; margin-right: auto; }}
  .paste-clear {{ position: absolute; top: 8px; right: 10px; background: #6e1c1c;
    color: #f85149; border: none; border-radius: 4px; padding: 3px 10px; font-size: 0.75em; cursor: pointer; }}
  /* Buttons */
  button {{ border: none; padding: 10px 20px; font-size: 0.88em; font-weight: 600;
    border-radius: 6px; cursor: pointer; transition: opacity 0.2s; }}
  button:hover {{ opacity: 0.8; }}
  .btn-primary {{ background: #238636; color: #fff; }}
  .btn-secondary {{ background: #1f6feb; color: #fff; }}
  .btn-ghost {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
  .btn-danger {{ background: #6e1c1c; color: #f85149; border: 1px solid #6e1c1c; font-size: 0.78em; padding: 4px 10px; }}
  .btn-sm {{ padding: 4px 12px; font-size: 0.78em; }}
  /* Lessons list */
  .lesson-card {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
    padding: 10px 12px; margin-bottom: 8px; display: flex; gap: 10px; }}
  .lesson-card.inactive {{ opacity: 0.4; }}
  .lesson-thumb {{ width: 72px; height: 54px; object-fit: cover; border-radius: 4px;
    border: 1px solid #30363d; flex-shrink: 0; background: #21262d; cursor: pointer; }}
  .lesson-thumb-empty {{ width: 72px; height: 54px; border-radius: 4px; border: 1px dashed #30363d;
    flex-shrink: 0; display: flex; align-items: center; justify-content: center;
    font-size: 1.3em; color: #30363d; }}
  .lesson-body {{ flex: 1; min-width: 0; }}
  .lesson-rule {{ font-size: 0.85em; color: #c9d1d9; line-height: 1.4; margin-bottom: 4px; }}
  .lesson-meta {{ font-size: 0.72em; color: #8b949e; }}
  .lesson-actions {{ display: flex; flex-direction: column; gap: 4px; align-items: flex-end; flex-shrink: 0; }}
  .cat-badge {{ display: inline-block; font-size: 0.7em; padding: 2px 7px; border-radius: 10px; font-weight: 600; }}
  .toggle {{ cursor: pointer; font-size: 1.1em; }}
  /* Image modal */
  .modal {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85);
    z-index: 100; align-items: center; justify-content: center; cursor: zoom-out; }}
  .modal.open {{ display: flex; }}
  .modal img {{ max-width: 95vw; max-height: 90vh; border-radius: 8px; border: 1px solid #30363d; }}
</style>
</head>
<body>

<a class="back-link" href="/">← Volver al Dashboard</a>
<h1>📚 Lecciones de Aprendizaje</h1>
<p class="subtitle">Randy enseña · Claude aprende · Se aplica en cada lectura</p>

<div class="panel">
  <h3>Nueva Lección</h3>
  <form class="lesson-form" method="POST" action="/add-lesson" enctype="multipart/form-data">
    <div id="paste-zone" class="paste-zone" tabindex="0">
      <span id="paste-label">📋 Pega tu capture de Quant Data aquí — <kbd style="background:#21262d;padding:2px 6px;border-radius:3px">Cmd+V</kbd> &nbsp;·&nbsp; o arrastra la imagen</span>
      <button type="button" class="paste-clear" id="paste-clear-btn" onclick="clearPaste(event)">✕ quitar</button>
      <img id="paste-preview" class="paste-preview" style="display:none">
    </div>
    <input type="hidden" name="image_data" id="image_data">
    <input type="hidden" name="image_mime" id="image_mime">
    <textarea name="lesson_text" id="lesson_text"
      placeholder="Describe qué pasó y qué quieres que el bot aprenda...&#10;ej: El precio estaba en $558 con zona magnética abajo pero el bot no advirtió del siguiente soporte a $554" required></textarea>
    <div class="form-row">
      <select name="category">
        <option value="General">General</option>
        <option value="DEX">DEX</option>
        <option value="GEX">GEX</option>
        <option value="Formato">Formato</option>
        <option value="Error detectado">Error detectado</option>
        <option value="Ejemplo bueno">Ejemplo bueno</option>
      </select>
      <button type="submit" class="btn-secondary">🧠 Analizar y Guardar</button>
    </div>
  </form>
</div>

<div class="panel">
  <h3>Lecciones guardadas ({total_lessons}) — {active_lessons} activas en Claude</h3>
  {lessons_html}
</div>

<!-- Image modal -->
<div class="modal" id="img-modal" onclick="this.classList.remove('open')">
  <img id="modal-img" src="">
</div>

<script>
(function() {{
  const zone = document.getElementById('paste-zone');
  const preview = document.getElementById('paste-preview');
  const clearBtn = document.getElementById('paste-clear-btn');
  const labelEl = document.getElementById('paste-label');
  const imgData = document.getElementById('image_data');
  const imgMime = document.getElementById('image_mime');
  const textarea = document.getElementById('lesson_text');

  function applyImage(file) {{
    if (!file || !file.type.startsWith('image/')) return;
    const reader = new FileReader();
    reader.onload = function(ev) {{
      const dataUrl = ev.target.result;
      imgData.value = dataUrl.split(',')[1];
      imgMime.value = file.type;
      preview.src = dataUrl;
      preview.style.display = 'block';
      zone.classList.add('has-image');
      zone.classList.remove('active');
      clearBtn.style.display = 'block';
      labelEl.textContent = '✅ Capture listo';
      textarea.focus();
    }};
    reader.readAsDataURL(file);
  }}

  document.addEventListener('paste', function(e) {{
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {{
      if (items[i].type.startsWith('image/')) {{
        e.preventDefault();
        applyImage(items[i].getAsFile());
        return;
      }}
    }}
  }});

  zone.addEventListener('dragover', function(e) {{ e.preventDefault(); zone.classList.add('active'); }});
  zone.addEventListener('dragleave', function() {{ zone.classList.remove('active'); }});
  zone.addEventListener('drop', function(e) {{
    e.preventDefault();
    zone.classList.remove('active');
    applyImage(e.dataTransfer.files[0]);
  }});
  zone.addEventListener('click', function() {{ zone.focus(); zone.classList.add('active'); }});
  zone.addEventListener('blur', function() {{ if (!imgData.value) zone.classList.remove('active'); }});
}})();

function clearPaste(e) {{
  e.stopPropagation();
  document.getElementById('image_data').value = '';
  document.getElementById('image_mime').value = '';
  document.getElementById('paste-preview').style.display = 'none';
  document.getElementById('paste-clear-btn').style.display = 'none';
  document.getElementById('paste-label').textContent = '📋 Pega tu capture de Quant Data aquí — Cmd+V · o arrastra la imagen';
  document.getElementById('paste-zone').classList.remove('has-image', 'active');
}}

function openModal(id) {{
  document.getElementById('modal-img').src = '/lesson-image/' + id;
  document.getElementById('img-modal').classList.add('open');
}}
</script>
</body>
</html>"""


CONFIRM_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QD Bot — Confirmar Lección</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', monospace; background: #0d1117; color: #c9d1d9; min-height: 100vh; padding: 20px; max-width: 700px; margin: 0 auto; }}
  h1 {{ font-size: 1.2em; color: #58a6ff; margin-bottom: 4px; }}
  .subtitle {{ color: #8b949e; font-size: 0.82em; margin-bottom: 24px; }}
  .section {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 16px; margin-bottom: 14px; }}
  .section h3 {{ color: #8b949e; font-size: 0.75em; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; }}
  .rule-box {{ font-size: 0.9em; color: #f0f6fc; line-height: 1.5; padding: 10px; background: #0d1117;
               border: 1px solid #1f6feb; border-radius: 6px; }}
  .summary-box {{ font-size: 0.82em; color: #8b949e; line-height: 1.5; margin-top: 8px; }}
  .question-box {{ font-size: 0.88em; color: #d29922; line-height: 1.5; padding: 10px;
                   background: #1a150d; border: 1px solid #d29922; border-radius: 6px; }}
  .cat-badge {{ display: inline-block; font-size: 0.75em; padding: 2px 8px; border-radius: 10px;
                font-weight: 600; margin-bottom: 8px; }}
  .orig-text {{ font-size: 0.8em; color: #8b949e; white-space: pre-wrap; line-height: 1.5;
                padding: 8px; background: #0d1117; border-radius: 4px; border: 1px solid #21262d; }}
  img.preview {{ max-width: 100%; border-radius: 6px; border: 1px solid #30363d; margin-top: 8px; }}
  textarea {{ width: 100%; background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
              color: #c9d1d9; padding: 8px 12px; font-size: 0.85em; resize: vertical;
              min-height: 60px; font-family: inherit; margin-top: 8px; }}
  textarea:focus {{ outline: none; border-color: #58a6ff; }}
  .btn-row {{ display: flex; gap: 10px; margin-top: 16px; }}
  button {{ border: none; padding: 10px 20px; font-size: 0.88em; font-weight: 600;
            border-radius: 6px; cursor: pointer; }}
  .btn-primary {{ background: #238636; color: #fff; }}
  .btn-ghost {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
  .analyzing {{ color: #58a6ff; font-size: 0.82em; }}
</style>
</head>
<body>
<h1>🧠 Claude analizó tu lección</h1>
<p class="subtitle">Revisa lo que aprendió y responde si hay alguna pregunta</p>

<div class="section">
  <h3>Regla extraída</h3>
  <span class="cat-badge" style="{cat_style}">{category}</span>
  <div class="rule-box">{rule}</div>
  {summary_html}
</div>

{question_section}

<div class="section">
  <h3>Tu descripción original</h3>
  <div class="orig-text">{orig_text}</div>
  {image_preview}
</div>

<form method="POST" action="/save-lesson">
  <input type="hidden" name="temp_id" value="{temp_id}">
  {answer_field}
  <div class="btn-row">
    <button type="submit" class="btn-primary">✅ Confirmar y Guardar</button>
    <a href="/"><button type="button" class="btn-ghost">Cancelar</button></a>
  </div>
</form>

</body>
</html>"""


CAT_STYLES = {
    "DEX": "background:#0d2137;color:#58a6ff",
    "GEX": "background:#0d2b1a;color:#3fb950",
    "Formato": "background:#1a1a2e;color:#8b8bff",
    "Error detectado": "background:#2b0d1a;color:#f85149",
    "Ejemplo bueno": "background:#0d2b1a;color:#3fb950",
    "General": "background:#21262d;color:#8b949e",
}


def _build_lessons(lessons: list) -> str:
    if not lessons:
        return '<p style="color:#8b949e;font-size:0.82em;padding:8px 0">Sin lecciones aún. Agrega tu primera observación arriba.</p>'
    html = ""
    for l in lessons:
        active = l.get("active", True)
        inactive_cls = "" if active else " inactive"
        toggle_action = "disable" if active else "enable"
        toggle_label = "⏸" if active else "▶"
        cat = l.get("category", "General")
        cat_key = cat.split()[0]  # "Error detectado" -> "Error"
        cat_style = CAT_STYLES.get(cat, CAT_STYLES["General"])
        rule_text = l.get("rule") or l.get("text", "")
        has_image = bool(l.get("image_type"))  # image_type always set if image uploaded
        # Check if lesson actually has an image by whether image_b64 would be non-empty
        # We check via a separate indicator stored in image_type being non-default OR
        # we add a has_image boolean. For now use a thumbnail endpoint.
        thumb_html = (
            f'<img class="lesson-thumb" src="/lesson-image/{l["id"]}" '
            f'onclick="openModal({l["id"]})" '
            f'onerror="this.style.display=\'none\';this.nextSibling.style.display=\'flex\'">'
            f'<div class="lesson-thumb-empty" style="display:none">📷</div>'
        )
        answer_html = ""
        if l.get("answer"):
            answer_html = f'<span style="color:#58a6ff"> · R: {l["answer"][:60]}...</span>' if len(l.get("answer","")) > 60 else f'<span style="color:#58a6ff"> · R: {l["answer"]}</span>'
        html += f'''<div class="lesson-card{inactive_cls}">
          {thumb_html}
          <div class="lesson-body">
            <div class="lesson-rule">{rule_text}</div>
            <div class="lesson-meta">
              <span class="cat-badge cat-{cat_key}" style="{cat_style};font-size:0.68em;padding:1px 6px">{cat}</span>
              #{l["id"]} · {l.get("created_at","")}{answer_html}
            </div>
          </div>
          <div class="lesson-actions">
            <form method="POST" action="/toggle-lesson-item" style="display:inline">
              <input type="hidden" name="lesson_id" value="{l["id"]}">
              <input type="hidden" name="action" value="{toggle_action}">
              <button class="btn-ghost btn-sm toggle" title="{"Desactivar" if active else "Activar"}">{toggle_label}</button>
            </form>
            <form method="POST" action="/delete-lesson-item" style="display:inline">
              <input type="hidden" name="lesson_id" value="{l["id"]}">
              <button class="btn-danger" onclick="return confirm('¿Eliminar esta leccion?')">✕</button>
            </form>
          </div>
        </div>'''
    return html


def _build_active_levels(data: dict) -> str:
    levels = data.get("active_levels", {})
    if not levels:
        return '<p style="color:#8b949e;font-size:0.82em">Sin niveles activos</p>'
    html = ""
    for ticker, info in levels.items():
        html += f'<div style="margin-bottom:10px"><strong>{ticker}</strong> <span style="color:#8b949e;font-size:0.75em">{info.get("updated","")}</span><br>'
        for s in info.get("supports", []):
            html += f'<span class="level-chip support">🟢 ${int(s)}</span>'
        for r in info.get("resistances", []):
            html += f'<span class="level-chip resistance">🔴 ${int(r)}</span>'
        html += '</div>'
    return html


def _build_history(data: dict) -> str:
    history = data.get("history", [])[:10]
    if not history:
        return '<p style="color:#8b949e;font-size:0.82em">Sin historial aún</p>'
    html = ""
    for h in history:
        badge_class = "green" if "Aguantó" in h["outcome"] else "red"
        html += f'''<div class="history-row">
          <span style="color:#8b949e">{h["time"]} {h["ticker"]}</span>
          <span style="color:#c9d1d9">${h["strike"]:.0f}</span>
          <span class="badge {badge_class}">{h["outcome"]}</span>
        </div>'''
    return html


def _build_rules(rules: list) -> str:
    if not rules:
        return '<p style="color:#8b949e;font-size:0.82em;padding:8px 0">Sin reglas aún. Agrega tu primera regla arriba.</p>'
    html = ""
    for r in rules:
        active = r.get("active", True)
        inactive_class = "" if active else " inactive"
        toggle_label = "⏸" if active else "▶"
        toggle_action = "disable" if active else "enable"
        cat = r.get("category", "General")
        html += f'''<div class="rule-card{inactive_class}">
          <div class="rule-header">
            <span class="cat-badge cat-{cat}">{cat}</span>
            <span class="rule-text">{r["text"]}</span>
            <form method="POST" action="/toggle-rule" style="display:inline">
              <input type="hidden" name="rule_id" value="{r['id']}">
              <input type="hidden" name="action" value="{toggle_action}">
              <button type="submit" class="btn-ghost btn-sm toggle" title="{"Desactivar" if active else "Activar"}">{toggle_label}</button>
            </form>
            <form method="POST" action="/delete-rule" style="display:inline">
              <input type="hidden" name="rule_id" value="{r['id']}">
              <button type="submit" class="btn-danger" onclick="return confirm('¿Eliminar esta regla?')">✕</button>
            </form>
          </div>
          <div class="rule-meta">#{r['id']} · {r.get("created_at","")}</div>
        </div>'''
    return html


def _build_darkpool_history(dp_history: list) -> str:
    if not dp_history:
        return '<p style="color:#8b949e;font-size:0.82em">Sin alertas de dark pool aún — el scanner activa a las 9:30 AM ET</p>'
    html = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:0.8em">'
    html += '<tr style="color:#8b949e;border-bottom:1px solid #30363d"><th style="text-align:left;padding:4px 8px">Hora</th><th style="text-align:left;padding:4px 8px">Ticker</th><th style="text-align:right;padding:4px 8px">Notional</th><th style="text-align:center;padding:4px 8px">Dir</th><th style="text-align:center;padding:4px 8px">Prints</th><th style="text-align:left;padding:4px 8px">Fecha</th></tr>'
    for e in dp_history[:20]:
        color = "#3fb950" if e["direction"] == "↑" else "#f85149"
        html += (
            f'<tr style="border-bottom:1px solid #21262d">'
            f'<td style="padding:5px 8px;color:#8b949e">{e["time"]}</td>'
            f'<td style="padding:5px 8px;font-weight:600;color:#f0f6fc">{e["ticker"]}</td>'
            f'<td style="padding:5px 8px;text-align:right;color:#58a6ff">${e["notional_m"]}M</td>'
            f'<td style="padding:5px 8px;text-align:center;color:{color};font-size:1.1em">{e["direction"]}</td>'
            f'<td style="padding:5px 8px;text-align:center;color:#8b949e">{e["prints"]}</td>'
            f'<td style="padding:5px 8px;color:#8b949e;font-size:0.85em">{e["date"]}</td>'
            f'</tr>'
        )
    html += '</table></div>'
    return html


def _build_discord_preview() -> str:
    if not _discord_preview:
        return '<div class="preview-empty">⏳ Aquí aparecerá el próximo mensaje que envíe el bot a Discord</div>'
    html = ""
    for m in _discord_preview:
        label = f"{m['tipo']}" + (f" · {m['label']}" if m['label'] else "")
        html += (
            f'<div class="preview-msg">'
            f'<div class="msg-meta">📤 {label} · {m["time"]}</div>'
            f'{m["text"]}'
            f'</div>'
        )
    return html


def _build_ask_result() -> str:
    if not _last_ask:
        return '<p style="color:#8b949e;font-size:0.82em;padding:4px 0">Escribe una pregunta arriba — el bot consultará los datos actuales del mercado para responderte.</p>'
    a = _last_ask
    return (
        f'<div style="background:#0d1117;border-left:3px solid #1f6feb;border-radius:0 8px 8px 0;'
        f'padding:11px 14px;font-size:0.86em;line-height:1.65;color:#c9d1d9">'
        f'<div style="color:#7cb9ff;font-size:0.72em;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.8px;margin-bottom:5px">🤖 Respuesta · {a["time"]}</div>'
        f'<div style="color:#8b949e;font-size:0.8em;margin-bottom:8px;font-style:italic">"{a["question"]}"</div>'
        f'{a["answer"]}'
        f'</div>'
    )


def _build_prompt_preview(prompt: str) -> str:
    if not prompt:
        return ""
    return f'''<div style="margin-top:10px">
      <div style="color:#8b949e;font-size:0.72em;margin-bottom:4px">PROMPT ACTIVO ENVIADO A CLAUDE:</div>
      <div class="active-prompt-preview">{prompt}</div>
    </div>'''


async def handle_index(request):
    now = datetime.now(ET)
    time_str = now.strftime("%I:%M:%S %p ET")
    data = st.get()
    accuracy = st.accuracy_pct()
    crit_data = cr.get_all()
    rules = crit_data.get("rules", [])
    active_rules = sum(1 for r in rules if r.get("active", True))
    all_lessons = ls.get_all()
    active_lessons_count = sum(1 for l in all_lessons if l.get("active", True))

    weekday = now.weekday()
    hour_min = now.hour * 60 + now.minute
    if weekday >= 5:
        market_status = "Fin de semana"
        dot_class = "red"
    elif hour_min < 9 * 60 + 25:
        market_status = "Pre-apertura"
        dot_class = "yellow"
    elif hour_min < 9 * 60 + 30:
        market_status = "Abriendo en minutos"
        dot_class = "yellow"
    elif hour_min < 16 * 60:
        market_status = "Mercado Abierto"
        dot_class = "green"
    else:
        market_status = "Mercado Cerrado"
        dot_class = "red"

    accuracy_color = "green" if accuracy >= 70 else "yellow" if accuracy >= 50 else "red"

    log_html = "".join(
        f'<div class="log-entry">{e}</div>' for e in reversed(_log[-5:])
    ) or '<div class="log-entry" style="color:#8b949e">Sin actividad aún</div>'

    disc_msgs = data.get("discord_messages", [])[-2:]
    discord_msgs_html = "".join(
        f'<div class="discord-msg"><div class="msg-header">📤 {m["tipo"]} · {m["ticker"]} · {m["time"]}</div>{m["text"]}</div>'
        for m in disc_msgs
    ) or '<p style="color:#8b949e;font-size:0.82em">Aún no hay mensajes</p>'

    html = HTML.format(
        time_et=time_str,
        market_status=market_status,
        dot_class=dot_class,
        last_ticker=data.get("last_ticker", "—"),
        last_price=f"{data.get('last_price', 0):.0f}" if data.get("last_price") else "—",
        last_msg_time=data.get("last_message_time", "—"),
        today_lecturas=data.get("today_lecturas", 0),
        total_lecturas=data.get("total_lecturas", 0),
        today_alertas=data.get("today_alertas", 0),
        total_alertas=data.get("total_alertas", 0),
        accuracy=accuracy,
        accuracy_color=accuracy_color,
        levels_held=data.get("levels_held", 0),
        levels_broken=data.get("levels_broken", 0),
        active_rules=active_rules,
        total_rules=len(rules),
        active_lessons=active_lessons_count,
        total_lessons=len(all_lessons),
        active_levels_html=_build_active_levels(data),
        history_html=_build_history(data),
        rules_html=_build_rules(rules),
        prompt_preview_html=_build_prompt_preview(crit_data.get("active_prompt", "")),
        discord_msgs_html=discord_msgs_html,
        log_html=log_html,
        preview_html=_build_discord_preview(),
        darkpool_history_html=_build_darkpool_history(data.get("darkpool_history", [])),
    )
    return web.Response(text=html, content_type="text/html")


async def handle_trigger(request):
    tipo = request.rel_url.query.get("tipo", "lectura")
    add_log(f"Boton presionado: {tipo} — callback={'OK' if _trigger_callback else 'NO REGISTRADO'}")
    if _trigger_callback:
        asyncio.create_task(_trigger_callback(tipo))
    else:
        add_log("[ERROR] Monitor loop no esta corriendo — reinicia el servicio en Railway")
    return await handle_index(request)


async def handle_domingo(request):
    if _domingo_callback:
        asyncio.create_task(_domingo_callback())
        add_log("Analisis dominical SPX iniciado desde el panel...")
    raise web.HTTPFound("/")


async def handle_reset_accuracy(request):
    import stats as st
    data = st._load()
    data["levels_held"] = 0
    data["levels_broken"] = 0
    data["history"] = []
    data["tested_today"] = {"date": "", "strikes": []}
    st._save(data)
    add_log("✅ Precisión reseteada — contadores en cero")
    raise web.HTTPFound("/")


async def handle_darkpool_status(request):
    try:
        import darkpool_scanner
        import config_manager
        import notifier
        add_log("Boton dark pool presionado...")
        status = darkpool_scanner.get_status()
        for line in status.split("\n"):
            add_log(line)
        config = config_manager.load()
        webhook = config.get("discord", {}).get("webhook_flujo_institucional", "")
        add_log(f"Webhook: {'...'+webhook[-20:] if webhook else 'NO CONFIGURADO'}")
        if webhook:
            ok = await notifier.send_webhook(webhook, status)
            if ok:
                add_log("Estado dark pool enviado a Discord ✅")
                add_discord_preview(status, "DARK POOL", "Estado")
            else:
                add_log("[ERROR] Discord rechazó el mensaje")
        else:
            add_log("[ERROR] Webhook flujo_institucional no configurado en Railway")
    except Exception as e:
        add_log(f"[ERROR] handle_darkpool_status: {e}")
    raise web.HTTPFound("/")


def _render_ask_page(question: str = "", answer: str = "", time_str: str = "") -> str:
    if answer:
        answer_section = (
            f'<div class="answer-box">'
            f'<div class="answer-meta">🤖 Respuesta de Randy · {time_str}</div>'
            f'<div class="answer-question">"{question}"</div>'
            f'<div class="answer-text">{answer}</div>'
            f'</div>'
        )
    else:
        answer_section = ""
    return ASK_PAGE_HTML.format(answer_section=answer_section,
                                prefill=question if not answer else "")


async def handle_ask_page(request):
    """GET /ask — página de consulta sin auto-refresh."""
    return web.Response(text=_render_ask_page(), content_type="text/html")


async def handle_ask(request):
    global _last_ask
    data = await request.post()
    question = data.get("question", "").strip()
    if not question:
        raise web.HTTPFound("/ask")

    add_log(f"Consulta recibida: {question[:60]}")

    stats_data = st.get()
    context = {
        "ticker": stats_data.get("last_ticker", "SPX"),
        "price": stats_data.get("last_price", 0),
        "nota": "Datos de la última lectura — pueden tener hasta 20 min de retraso",
    }

    try:
        import qd_client
        import config_manager
        import analyzer
        import aiohttp as _aiohttp
        cfg = config_manager.load()
        api_key = cfg.get("quantdata", {}).get("api_key", "")
        ticker = cfg.get("tickers", ["SPX"])[0]
        if api_key:
            async with _aiohttp.ClientSession() as s:
                market_data, enriched = await asyncio.gather(
                    qd_client.fetch_market_data(ticker, s, api_key),
                    qd_client.fetch_enriched_context(ticker, s, api_key),
                    return_exceptions=True,
                )
            if not isinstance(market_data, Exception) and market_data and market_data.get("price"):
                analysis = analyzer.analyze(market_data)
                sesgo = analysis.get("sesgo", {})
                gex_flip = analysis.get("gex_flip")
                dex_flip = analysis.get("dex_flip")
                zonas = analysis.get("zonas_fuertes", {})
                context.update({
                    "ticker": ticker,
                    "price": market_data.get("price"),
                    "sesgo": sesgo.get("sesgo", "NEUTRAL"),
                    "fuerza": sesgo.get("strength", ""),
                    "mvc": int(dex_flip["strike"]) if dex_flip else None,
                    "precio_sobre_mvc": dex_flip.get("price_above_flip") if dex_flip else None,
                    "gamma_flip_pivote": int(gex_flip["strike"]) if gex_flip else None,
                    "soportes_clave": [int(z["strike"]) for z in zonas.get("top_supports", [])],
                    "resistencias_clave": [int(z["strike"]) for z in zonas.get("top_resistances", [])],
                })
                context.pop("nota", None)
            if not isinstance(enriched, Exception) and enriched:
                context["vix"] = enriched.get("vix")
                context["flow_bias"] = enriched.get("flow_bias", {})
            add_log(f"Datos para consulta — ${context.get('price','?')} · MVC ${context.get('mvc','?')}")
    except Exception as e:
        add_log(f"[WARN] Usando datos en caché: {e}")

    answer = ""
    now_str = datetime.now(ET).strftime("%I:%M %p ET")
    if not _anthropic_key:
        answer = "No tengo conexión con el modelo ahora. Revisa la configuración."
        add_log("[ERROR] Anthropic key no configurada")
    else:
        try:
            answer = await claude_client.answer_market_question(question, context, _anthropic_key)
            _last_ask = {"question": question, "answer": answer, "time": now_str}
            st.record_question(question, answer)
            add_log("Consulta respondida ✅")
        except Exception as e:
            answer = "Algo salió mal al consultar. Intenta de nuevo."
            add_log(f"[ERROR] handle_ask: {e}")

    return web.Response(text=_render_ask_page(question, answer, now_str),
                        content_type="text/html")


async def handle_questions_page(request):
    """GET /preguntas — muestra formulario de contraseña."""
    content = """
    <div class="auth-box">
      <h2>🔒 Acceso Restringido</h2>
      <form method="POST" action="/preguntas">
        <input type="password" name="pwd" placeholder="••••" autofocus style="letter-spacing:0.3em;font-size:1.4rem;width:100%;padding:10px;border:1px solid #333;border-radius:6px;background:#1a1a1a;color:#fff;text-align:center;margin-bottom:12px;">
        <button type="submit" style="width:100%;padding:10px;background:#2563eb;color:#fff;border:none;border-radius:6px;font-size:1rem;cursor:pointer;">Entrar</button>
      </form>
    </div>"""
    html = QUESTIONS_LOG_HTML.format(total=0, content=content)
    return web.Response(text=html, content_type="text/html")


async def handle_questions_auth(request):
    """POST /preguntas — valida contraseña y muestra log de preguntas."""
    data = await request.post()
    if data.get("pwd", "") != RULES_PASSWORD:
        content = """
    <div class="auth-box">
      <h2>🔒 Contraseña incorrecta</h2>
      <form method="POST" action="/preguntas">
        <input type="password" name="pwd" placeholder="••••" autofocus style="letter-spacing:0.3em;font-size:1.4rem;width:100%;padding:10px;border:1px solid #c00;border-radius:6px;background:#1a1a1a;color:#fff;text-align:center;margin-bottom:12px;">
        <button type="submit" style="width:100%;padding:10px;background:#2563eb;color:#fff;border:none;border-radius:6px;font-size:1rem;cursor:pointer;">Entrar</button>
      </form>
    </div>"""
        html = QUESTIONS_LOG_HTML.format(total=0, content=content)
        return web.Response(text=html, content_type="text/html")

    questions = st.get().get("questions_log", [])
    today_str = date.today().isoformat()
    today_count = sum(1 for q in questions if q.get("date") == today_str)

    cards_html = ""
    if not questions:
        cards_html = "<p style='color:#666;text-align:center;margin-top:40px;'>Aún no hay preguntas registradas.</p>"
    else:
        for q in questions:
            question_text = q.get("question", "")
            answer_text = q.get("answer", "")
            time_str = q.get("time", "")
            date_str = q.get("date", "")
            cards_html += f"""
        <div class="q-card">
          <div class="q-meta">{date_str} · {time_str}</div>
          <div class="q-text">❓ {question_text}</div>
          <div class="q-answer">💬 {answer_text}</div>
        </div>"""

    content = f"""
    <div class="stats-bar">
      <div class="stat"><div class="n">{len(questions)}</div><div class="l">Total</div></div>
      <div class="stat"><div class="n">{today_count}</div><div class="l">Hoy</div></div>
    </div>
    <input type="text" id="search" placeholder="Filtrar preguntas..." oninput="filterQ()"
      style="width:100%;padding:8px 12px;margin-bottom:16px;border:1px solid #333;border-radius:6px;background:#1a1a1a;color:#fff;font-size:0.9rem;">
    <div id="q-list">
      {cards_html}
    </div>"""

    html = QUESTIONS_LOG_HTML.format(total=len(questions), content=content)
    return web.Response(text=html, content_type="text/html")


async def handle_add_rule(request):
    data = await request.post()
    if data.get("password", "") != RULES_PASSWORD:
        add_log("[ERROR] Clave incorrecta — regla no agregada")
        raise web.HTTPFound("/")
    text = data.get("rule_text", "").strip()
    category = data.get("category", "General")
    if text:
        final_text = text
        if _anthropic_key:
            try:
                refined = await claude_client.refine_rule(text, _anthropic_key)
                if refined and refined != text:
                    add_log(f"Regla refinada por IA: {refined[:60]}")
                    final_text = refined
            except Exception as e:
                add_log(f"[WARN] No se pudo refinar regla: {e}")
        rule = cr.add_rule(final_text, category)
        add_log(f"Regla #{rule['id']} [{category}] guardada")
    raise web.HTTPFound("/")


async def handle_toggle_rule(request):
    data = await request.post()
    rule_id = int(data.get("rule_id", 0))
    action = data.get("action", "enable")
    if rule_id:
        cr.toggle_rule(rule_id, action == "enable")
        add_log(f"Regla #{rule_id} {'activada' if action == 'enable' else 'desactivada'}")
    raise web.HTTPFound("/")


async def handle_delete_rule(request):
    data = await request.post()
    rule_id = int(data.get("rule_id", 0))
    if rule_id:
        cr.delete_rule(rule_id)
        add_log(f"Regla #{rule_id} eliminada")
    raise web.HTTPFound("/")


async def handle_lessons_page(request):
    all_lessons = ls.get_all()
    active_count = sum(1 for l in all_lessons if l.get("active", True))
    html = LESSONS_HTML.format(
        total_lessons=len(all_lessons),
        active_lessons=active_count,
        lessons_html=_build_lessons(all_lessons),
    )
    return web.Response(text=html, content_type="text/html")


async def handle_add_lesson(request):
    data = await request.post()
    text = data.get("lesson_text", "").strip()
    category = data.get("category", "General")
    if not text:
        raise web.HTTPFound("/")

    image_b64 = ""
    image_type = "image/png"
    # Clipboard paste (base64 sent via hidden input)
    pasted_b64 = data.get("image_data", "").strip()
    if pasted_b64:
        image_b64 = pasted_b64
        image_type = data.get("image_mime", "image/png") or "image/png"
    else:
        # Fallback: file upload
        image_field = data.get("image")
        if image_field and hasattr(image_field, "file"):
            img_bytes = image_field.file.read()
            if img_bytes:
                image_b64 = base64.b64encode(img_bytes).decode()
                image_type = image_field.content_type or "image/png"

    add_log("Analizando leccion con Claude...")
    analysis = {"regla": text, "categoria": category, "resumen": "", "pregunta": ""}
    if _anthropic_key:
        try:
            analysis = await claude_client.analyze_lesson(image_b64, image_type, text, _anthropic_key)
            add_log(f"Leccion analizada — regla: {analysis['regla'][:60]}")
        except Exception as e:
            add_log(f"[WARN] Error analizando leccion: {e}")

    temp_id = str(uuid.uuid4())[:8]
    _pending_lessons[temp_id] = {
        "text": text,
        "image_b64": image_b64,
        "image_type": image_type,
        "rule": analysis["regla"],
        "category": analysis.get("categoria", category),
        "summary": analysis.get("resumen", ""),
        "question": analysis.get("pregunta", ""),
    }
    raise web.HTTPFound(f"/confirm-lesson/{temp_id}")


async def handle_confirm_lesson(request):
    temp_id = request.match_info["temp_id"]
    pending = _pending_lessons.get(temp_id)
    if not pending:
        raise web.HTTPFound("/")

    cat = pending["category"]
    cat_style = CAT_STYLES.get(cat, CAT_STYLES["General"])

    summary_html = (
        f'<div class="summary-box">{pending["summary"]}</div>'
        if pending.get("summary") else ""
    )

    question = pending.get("question", "")
    if question:
        question_section = f'''<div class="section">
          <h3>Pregunta de Claude</h3>
          <div class="question-box">❓ {question}</div>
          <textarea name="answer_preview" placeholder="Tu respuesta (opcional)..." disabled style="opacity:0.5"></textarea>
        </div>'''
        answer_field = f'''<div style="margin-bottom:12px">
          <div style="color:#d29922;font-size:0.82em;margin-bottom:6px">❓ {question}</div>
          <textarea name="answer" placeholder="Tu respuesta (opcional — ayuda a Claude a aplicar la regla mejor)..."></textarea>
        </div>'''
    else:
        question_section = ""
        answer_field = '<input type="hidden" name="answer" value="">'

    image_preview = ""
    if pending.get("image_b64"):
        img_data = pending["image_b64"]
        img_type = pending.get("image_type", "image/png")
        image_preview = f'<img class="preview" src="data:{img_type};base64,{img_data}">'

    html = CONFIRM_HTML.format(
        temp_id=temp_id,
        rule=pending["rule"],
        category=cat,
        cat_style=cat_style,
        summary_html=summary_html,
        question_section=question_section,
        answer_field=answer_field,
        orig_text=pending["text"],
        image_preview=image_preview,
    )
    return web.Response(text=html, content_type="text/html")


async def handle_save_lesson(request):
    data = await request.post()
    temp_id = data.get("temp_id", "")
    answer = data.get("answer", "").strip()
    pending = _pending_lessons.pop(temp_id, None)
    if not pending:
        raise web.HTTPFound("/")

    lesson = ls.add_lesson(
        text=pending["text"],
        rule=pending["rule"],
        category=pending["category"],
        summary=pending["summary"],
        question=pending["question"],
        answer=answer,
        image_b64=pending.get("image_b64", ""),
        image_type=pending.get("image_type", "image/png"),
    )
    add_log(f"Leccion #{lesson.get('id')} guardada [{pending['category']}]")
    raise web.HTTPFound("/")


async def handle_lesson_image(request):
    lesson_id = int(request.match_info["lesson_id"])
    img_b64, img_type = ls.get_image(lesson_id)
    if not img_b64:
        raise web.HTTPNotFound()
    img_bytes = base64.b64decode(img_b64)
    return web.Response(body=img_bytes, content_type=img_type or "image/png")


async def handle_toggle_lesson_item(request):
    data = await request.post()
    lesson_id = int(data.get("lesson_id", 0))
    action = data.get("action", "enable")
    if lesson_id:
        ls.toggle_lesson(lesson_id, action == "enable")
        add_log(f"Leccion #{lesson_id} {'activada' if action == 'enable' else 'desactivada'}")
    raise web.HTTPFound("/")


async def handle_delete_lesson_item(request):
    data = await request.post()
    lesson_id = int(data.get("lesson_id", 0))
    if lesson_id:
        ls.delete_lesson(lesson_id)
        add_log(f"Leccion #{lesson_id} eliminada")
    raise web.HTTPFound("/")


def create_app() -> web.Application:
    app = web.Application(client_max_size=10 * 1024 * 1024)  # 10MB max upload
    app.router.add_get("/", handle_index)
    app.router.add_post("/trigger", handle_trigger)
    app.router.add_post("/domingo", handle_domingo)
    app.router.add_post("/darkpool-status", handle_darkpool_status)
    app.router.add_post("/reset-accuracy", handle_reset_accuracy)
    app.router.add_get("/ask", handle_ask_page)
    app.router.add_post("/ask", handle_ask)
    app.router.add_get("/preguntas", handle_questions_page)
    app.router.add_post("/preguntas", handle_questions_auth)
    app.router.add_post("/add-rule", handle_add_rule)
    app.router.add_post("/toggle-rule", handle_toggle_rule)
    app.router.add_post("/delete-rule", handle_delete_rule)
    app.router.add_get("/lessons", handle_lessons_page)
    app.router.add_post("/add-lesson", handle_add_lesson)
    app.router.add_get("/confirm-lesson/{temp_id}", handle_confirm_lesson)
    app.router.add_post("/save-lesson", handle_save_lesson)
    app.router.add_get("/lesson-image/{lesson_id}", handle_lesson_image)
    app.router.add_post("/toggle-lesson-item", handle_toggle_lesson_item)
    app.router.add_post("/delete-lesson-item", handle_delete_lesson_item)
    return app


async def start_dashboard(port: int = 8080):
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    add_log(f"Dashboard iniciado en puerto {port}")
