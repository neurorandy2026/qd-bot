from aiohttp import web
from datetime import datetime
from zoneinfo import ZoneInfo
import stats as st
import criteria as cr
import claude_client

ET = ZoneInfo("America/New_York")
_log: list = []
_trigger_callback = None
_anthropic_key: str = ""


def set_trigger_callback(fn):
    global _trigger_callback
    _trigger_callback = fn


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


HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QD Bot</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', monospace; background: #0d1117; color: #c9d1d9; min-height: 100vh; padding: 20px; }}
  h1 {{ font-size: 1.3em; color: #58a6ff; margin-bottom: 4px; }}
  .subtitle {{ color: #8b949e; font-size: 0.82em; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px; }}
  .card .label {{ color: #8b949e; font-size: 0.75em; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }}
  .card .value {{ font-size: 1.8em; font-weight: bold; color: #f0f6fc; }}
  .card .value.green {{ color: #3fb950; }}
  .card .value.yellow {{ color: #d29922; }}
  .card .value.blue {{ color: #58a6ff; }}
  .card .value.red {{ color: #f85149; }}
  .card .sub {{ color: #8b949e; font-size: 0.78em; margin-top: 4px; }}
  .status-bar {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 12px 16px;
                 display: flex; align-items: center; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .dot.green {{ background: #3fb950; box-shadow: 0 0 6px #3fb950; }}
  .dot.red {{ background: #f85149; }}
  .dot.yellow {{ background: #d29922; box-shadow: 0 0 6px #d29922; animation: pulse 1.5s infinite; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.5}} }}
  .btn-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }}
  button {{ border: none; padding: 10px 20px; font-size: 0.88em; font-weight: 600;
            border-radius: 6px; cursor: pointer; transition: opacity 0.2s; }}
  button:hover {{ opacity: 0.8; }}
  .btn-primary {{ background: #238636; color: #fff; }}
  .btn-secondary {{ background: #1f6feb; color: #fff; }}
  .btn-ghost {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
  .btn-danger {{ background: #6e1c1c; color: #f85149; border: 1px solid #6e1c1c; font-size: 0.78em; padding: 4px 10px; }}
  .btn-sm {{ padding: 4px 12px; font-size: 0.78em; }}
  .panels {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  @media(max-width: 600px) {{ .panels {{ grid-template-columns: 1fr; }} }}
  .panel {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px; }}
  .panel h3 {{ color: #8b949e; font-size: 0.78em; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }}
  .log-entry {{ font-size: 0.78em; padding: 5px 0; border-bottom: 1px solid #21262d; color: #8b949e; }}
  .log-entry:first-child {{ color: #c9d1d9; }}
  .log-entry:last-child {{ border-bottom: none; }}
  .level-chip {{ display: inline-block; background: #21262d; border-radius: 4px; padding: 2px 8px;
                 font-size: 0.82em; margin: 2px; border: 1px solid #30363d; }}
  .level-chip.support {{ border-color: #3fb950; color: #3fb950; }}
  .level-chip.resistance {{ border-color: #f85149; color: #f85149; }}
  .history-row {{ display: flex; justify-content: space-between; font-size: 0.8em; padding: 4px 0;
                  border-bottom: 1px solid #21262d; }}
  .history-row:last-child {{ border-bottom: none; }}
  .badge {{ padding: 2px 8px; border-radius: 10px; font-size: 0.75em; font-weight: 600; }}
  .badge.green {{ background: #0d4429; color: #3fb950; }}
  .badge.red {{ background: #3d0f0f; color: #f85149; }}
  .accuracy-bar {{ background: #21262d; border-radius: 4px; height: 8px; margin-top: 6px; overflow: hidden; }}
  .accuracy-fill {{ height: 100%; background: #3fb950; border-radius: 4px; transition: width 0.5s; }}
  .discord-msg {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 10px 12px;
                  margin-bottom: 8px; font-size: 0.78em; white-space: pre-wrap; line-height: 1.5; }}
  .discord-msg .msg-header {{ color: #8b949e; font-size: 0.85em; margin-bottom: 6px; }}
  /* Criteria styles */
  .criteria-form {{ display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }}
  .criteria-form input[type=text] {{ flex: 1; min-width: 200px; background: #0d1117; border: 1px solid #30363d;
    border-radius: 6px; color: #c9d1d9; padding: 8px 12px; font-size: 0.85em; }}
  .criteria-form input[type=text]:focus {{ outline: none; border-color: #58a6ff; }}
  .criteria-form select {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    color: #c9d1d9; padding: 8px; font-size: 0.85em; }}
  .rule-card {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 10px 12px;
                margin-bottom: 8px; }}
  .rule-card.inactive {{ opacity: 0.4; }}
  .rule-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
  .rule-text {{ font-size: 0.85em; color: #c9d1d9; flex: 1; line-height: 1.4; }}
  .cat-badge {{ font-size: 0.7em; padding: 2px 7px; border-radius: 10px; font-weight: 600; white-space: nowrap; }}
  .cat-DEX {{ background: #0d2137; color: #58a6ff; }}
  .cat-GEX {{ background: #0d2b1a; color: #3fb950; }}
  .cat-Mensajes {{ background: #2b1f0d; color: #d29922; }}
  .cat-Alertas {{ background: #2b0d1a; color: #f85149; }}
  .cat-General {{ background: #21262d; color: #8b949e; }}
  .rule-meta {{ font-size: 0.72em; color: #8b949e; margin-top: 3px; }}
  .toggle {{ cursor: pointer; font-size: 1.1em; }}
  .active-prompt-preview {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    padding: 8px 12px; font-size: 0.75em; color: #8b949e; white-space: pre-wrap;
    max-height: 80px; overflow-y: auto; margin-bottom: 10px; }}
</style>
</head>
<body>

<h1>📊 QD Bot — Panel de Control</h1>
<p class="subtitle">Lector de mercado en tiempo real · Actualiza cada 30s</p>

<div class="status-bar">
  <span class="dot {dot_class}"></span>
  <strong>{market_status}</strong>
  <span style="color:#8b949e">·</span>
  <span style="color:#8b949e">{time_et}</span>
  <span style="color:#8b949e">·</span>
  <span>{last_ticker} <strong style="color:#58a6ff">${last_price}</strong></span>
  <span style="color:#8b949e;font-size:0.8em">Último msg: {last_msg_time}</span>
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
</div>

<div class="btn-row">
  <form method="POST" action="/trigger" style="display:inline">
    <button type="submit" class="btn-primary">📤 Enviar Lectura Ahora</button>
  </form>
  <form method="POST" action="/trigger?tipo=apertura" style="display:inline">
    <button type="submit" class="btn-secondary">🌅 Apertura</button>
  </form>
  <form method="POST" action="/trigger?tipo=cierre" style="display:inline">
    <button type="submit" class="btn-ghost">🔔 Cierre</button>
  </form>
</div>

<div class="panels">
  <div class="panel">
    <h3>📍 Niveles Activos</h3>
    {active_levels_html}
  </div>
  <div class="panel">
    <h3>🎯 Historial de Niveles</h3>
    {history_html}
  </div>
</div>

<div class="panel" style="margin-top:12px">
  <h3>🧠 Criterio del Instructor — Reglas Activas en Claude</h3>

  <form class="criteria-form" method="POST" action="/add-rule">
    <input type="text" name="rule_text" placeholder="Nueva regla... ej: Si hay zona magnética de 3 strikes, mencionar el target exacto" required>
    <select name="category">
      <option value="General">General</option>
      <option value="DEX">DEX</option>
      <option value="GEX">GEX</option>
      <option value="Mensajes">Mensajes</option>
      <option value="Alertas">Alertas</option>
    </select>
    <button type="submit" class="btn-primary btn-sm">+ Agregar</button>
  </form>

  {rules_html}

  {prompt_preview_html}
</div>

<div class="panels" style="margin-top:12px">
  <div class="panel">
    <h3>💬 Últimos Mensajes a Discord</h3>
    {discord_msgs_html}
  </div>
  <div class="panel">
    <h3>📋 Log del Bot</h3>
    {log_html}
  </div>
</div>

<script>setTimeout(() => location.reload(), 30000);</script>
</body>
</html>"""


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
        f'<div class="log-entry">{e}</div>' for e in reversed(_log[-20:])
    ) or '<div class="log-entry" style="color:#8b949e">Sin actividad aún</div>'

    disc_msgs = data.get("discord_messages", [])
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
        active_levels_html=_build_active_levels(data),
        history_html=_build_history(data),
        rules_html=_build_rules(rules),
        prompt_preview_html=_build_prompt_preview(crit_data.get("active_prompt", "")),
        discord_msgs_html=discord_msgs_html,
        log_html=log_html,
    )
    return web.Response(text=html, content_type="text/html")


async def handle_trigger(request):
    tipo = request.rel_url.query.get("tipo", "lectura")
    if _trigger_callback:
        import asyncio
        asyncio.create_task(_trigger_callback(tipo))
        add_log(f"Disparo manual ({tipo}) desde el panel")
    raise web.HTTPFound("/")


async def handle_add_rule(request):
    data = await request.post()
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


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/trigger", handle_trigger)
    app.router.add_post("/add-rule", handle_add_rule)
    app.router.add_post("/toggle-rule", handle_toggle_rule)
    app.router.add_post("/delete-rule", handle_delete_rule)
    return app


async def start_dashboard(port: int = 8080):
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    add_log(f"Dashboard iniciado en puerto {port}")
