import base64
import uuid
from aiohttp import web
from datetime import datetime
from zoneinfo import ZoneInfo
import stats as st
import criteria as cr
import lessons as ls
import claude_client

ET = ZoneInfo("America/New_York")
_log: list = []
_trigger_callback = None
_anthropic_key: str = ""
_pending_lessons: dict = {}  # temp_id -> pending lesson data


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
  /* Lessons styles */
  .lesson-form {{ display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }}
  .lesson-form textarea {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    color: #c9d1d9; padding: 8px 12px; font-size: 0.85em; resize: vertical; min-height: 70px;
    font-family: inherit; }}
  .lesson-form textarea:focus {{ outline: none; border-color: #58a6ff; }}
  .lesson-form-row {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .lesson-form input[type=file] {{ flex: 1; color: #8b949e; font-size: 0.82em; }}
  .lesson-form select {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    color: #c9d1d9; padding: 8px; font-size: 0.85em; }}
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
  <div class="card">
    <div class="label">Lecciones Activas</div>
    <div class="value blue">{active_lessons}</div>
    <div class="sub">de {total_lessons} lecciones</div>
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

<div class="panel" style="margin-top:12px">
  <h3>📚 Lecciones de Aprendizaje — Randy enseña, Claude aprende</h3>
  <p class="lesson-count">Las lecciones activas se inyectan como contexto visual en cada lectura que genera Claude.</p>

  <form class="lesson-form" method="POST" action="/add-lesson" enctype="multipart/form-data">
    <textarea name="lesson_text" placeholder="Describe qué pasó y qué quieres que el bot aprenda... ej: Aquí el precio rebotó en $755 pero el bot no mencionó la zona magnética que había 3 strikes abajo" required></textarea>
    <div class="lesson-form-row">
      <input type="file" name="image" accept="image/*">
      <select name="category">
        <option value="General">General</option>
        <option value="DEX">DEX</option>
        <option value="GEX">GEX</option>
        <option value="Formato">Formato</option>
        <option value="Error detectado">Error detectado</option>
        <option value="Ejemplo bueno">Ejemplo bueno</option>
      </select>
      <button type="submit" class="btn-secondary btn-sm">🧠 Analizar y Guardar</button>
    </div>
  </form>

  {lessons_html}
</div>

<script>setTimeout(() => location.reload(), 30000);</script>
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


CAT_STYLES = {{
    "DEX": "background:#0d2137;color:#58a6ff",
    "GEX": "background:#0d2b1a;color:#3fb950",
    "Formato": "background:#1a1a2e;color:#8b8bff",
    "Error detectado": "background:#2b0d1a;color:#f85149",
    "Ejemplo bueno": "background:#0d2b1a;color:#3fb950",
    "General": "background:#21262d;color:#8b949e",
}}


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
        active_lessons=active_lessons_count,
        total_lessons=len(all_lessons),
        active_levels_html=_build_active_levels(data),
        history_html=_build_history(data),
        rules_html=_build_rules(rules),
        prompt_preview_html=_build_prompt_preview(crit_data.get("active_prompt", "")),
        discord_msgs_html=discord_msgs_html,
        log_html=log_html,
        lessons_html=_build_lessons(all_lessons),
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


async def handle_add_lesson(request):
    data = await request.post()
    text = data.get("lesson_text", "").strip()
    category = data.get("category", "General")
    if not text:
        raise web.HTTPFound("/")

    image_b64 = ""
    image_type = "image/png"
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
    app.router.add_post("/add-rule", handle_add_rule)
    app.router.add_post("/toggle-rule", handle_toggle_rule)
    app.router.add_post("/delete-rule", handle_delete_rule)
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
