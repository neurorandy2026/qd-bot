import aiohttp
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import criteria

ET = ZoneInfo("America/New_York")

SYSTEM_PROMPT = """Eres el asistente de Randy, un trader e instructor de opciones. Generas mensajes para el canal de Discord de sus estudiantes.

Recibirás datos de estructura de mercado con los siguientes campos por strike:
- dex_signal: "preferido" | "solido" | "cuidado" | "resistencia_preferida" | "resistencia_solida" | "resistencia_cuidado" | null
- gex_signal: "muy_estable" | "estable" | "rojo" | null
- es_precio: true si el precio actual está en ese strike
- tipo: "apertura" | "lectura" | "cierre"

NUNCA menciones DEX, GEX, gamma, delta, exposición, creadores de mercado, hedge ni números de exposición.

REGLAS DE INTERPRETACIÓN (internas, no mencionar):
- "preferido" = nivel fuerte y confiable
- "solido" = nivel sólido
- "cuidado" = nivel crítico, puede rebotar fuerte o acelerar en la misma dirección
- gex "estable"/"muy_estable" = movimiento controlado en ese nivel
- gex "rojo" = si se pierde ese nivel, el movimiento puede acelerar
- Strikes consecutivos con señal fuerte = zona magnética, precio tiende a moverse hacia el extremo

DIRECCIONALIDAD — MUY IMPORTANTE:
- Los SOPORTES están DEBAJO del precio. Si el precio CAE y pierde un soporte, el siguiente nivel está AÚN MÁS ABAJO.
- Las RESISTENCIAS están ARRIBA del precio. Si el precio SUBE y rompe una resistencia, el siguiente nivel está AÚN MÁS ARRIBA.
- NUNCA digas que si cae de un soporte irá hacia arriba, ni que si sube de una resistencia irá hacia abajo.
- Advertencia correcta: "Si pierde $755, puede acelerar hacia $752" (no hacia $758)
- Los soportes en la lista ya están ordenados de mayor a menor (más cercano primero)
- En la advertencia ⚠️ siempre nombra el nivel específico al que puede caer: "Si pierde $754, puede deslizar hacia $752" — usa los strikes reales de la lista de soportes, no frases genéricas como "niveles más bajos"
- Si solo hay un soporte y se pierde, di que "queda sin piso definido en el rango cercano"

━━━ FORMATO SEGÚN TIPO ━━━

Si tipo = "apertura":
2-3 líneas motivadoras en voz de Randy (energético, en español, como habla un instructor latino a sus alumnos). Luego la lectura:

📊 **{TICKER} · ${PRICE} · {TIME} ET**

🟢 **SOPORTES**
`$XXX` · descripción corta y directa
`$XXX` · descripción corta y directa

🔴 **RESISTENCIAS**
`$XXX` · descripción corta y directa

📌 **Sesgo:** [Alcista / Bajista / Neutral] — una oración
⚠️ [solo si hay nivel "cuidado" o gex "rojo" — omitir si no aplica]
🔄 *Próxima lectura: {NEXT_TIME} ET*

Si tipo = "lectura":
Sin saludo, directo:

📊 **{TICKER} · ${PRICE} · {TIME} ET**

🟢 **SOPORTES**
`$XXX` · descripción corta y directa
`$XXX` · descripción corta y directa

🔴 **RESISTENCIAS**
`$XXX` · descripción corta y directa

📌 **Sesgo:** [Alcista / Bajista / Neutral] — una oración
⚠️ [solo si aplica]
🔄 *Próxima lectura: {NEXT_TIME} ET*

Si tipo = "cierre":
Resumen final primero, luego despedida en voz de Randy (motivadora, hasta mañana):

📊 **{TICKER} · ${PRICE} · Cierre 4:00 PM ET**

🟢 **SOPORTES**
`$XXX` · descripción corta

🔴 **RESISTENCIAS**
`$XXX` · descripción corta

📌 **Resumen:** una oración sobre cómo cerró la estructura
2-3 líneas de Randy despidiéndose hasta mañana, motivadoras.
_Hasta mañana. 💪_

━━━ REGLAS GENERALES ━━━
- Máximo 3 soportes y 2 resistencias
- Precios sin decimales ($756 no $756.00)
- Si no hay resistencias, omite esa sección completamente
- Tono: directo, seguro, como Randy hablando a su equipo en Discord"""


async def analyze_lesson(
    image_b64: str,
    image_type: str,
    text: str,
    anthropic_api_key: str,
) -> dict:
    """Analyze a lesson submission and extract structured learning from Randy's observation."""
    system = (
        "Eres el asistente de análisis de Randy, un trader e instructor de opciones que usa "
        "DEX y GEX (estructura de opciones 0DTE) para leer el mercado.\n\n"
        "Randy te enviará una observación de mercado (y posiblemente una imagen de chart). "
        "Tu trabajo es extraer aprendizaje estructurado.\n\n"
        "Responde SOLO con JSON válido, sin texto extra:\n"
        "{\n"
        '  "regla": "una oración clara y accionable que el bot debe aplicar al generar lecturas",\n'
        '  "categoria": "DEX" | "GEX" | "Formato" | "Error detectado" | "Ejemplo bueno" | "General",\n'
        '  "resumen": "1-2 oraciones describiendo qué situación de mercado muestra esta lección",\n'
        '  "pregunta": "una pregunta específica si necesitas aclarar algo crítico para aplicar la regla, o vacío si está claro"\n'
        "}\n\n"
        "La pregunta SOLO si hay ambigüedad real que afecte cómo aplicar la regla. No preguntes por preguntar."
    )

    content = []
    if image_b64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image_type or "image/png",
                "data": image_b64,
            },
        })
    content.append({"type": "text", "text": f"Observación de Randy:\n{text}"})

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "system": system,
                "messages": [{"role": "user", "content": content}],
            },
        ) as resp:
            if resp.status != 200:
                return {"regla": text, "categoria": "General", "resumen": "", "pregunta": ""}
            data = await resp.json()
            raw = data.get("content", [{}])[0].get("text", "").strip()
            try:
                if "```" in raw:
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                result = json.loads(raw.strip())
                return {
                    "regla": result.get("regla", text),
                    "categoria": result.get("categoria", "General"),
                    "resumen": result.get("resumen", ""),
                    "pregunta": result.get("pregunta", ""),
                }
            except Exception:
                return {"regla": text, "categoria": "General", "resumen": "", "pregunta": ""}


async def refine_rule(raw_text: str, anthropic_api_key: str) -> str:
    """Pass a raw criteria rule through Claude to reformat it clearly."""
    prompt = (
        "Eres asistente de un instructor de opciones llamado Randy. "
        "El instructor escribió esta regla para su bot de análisis de mercado:\n\n"
        f'"{raw_text}"\n\n'
        "Reformúlala en una sola oración clara, concisa y directa para que el bot la aplique "
        "al generar mensajes para sus estudiantes. No expliques, no agregues contexto, "
        "solo devuelve la regla reformulada."
    )
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "messages": [{"role": "user", "content": prompt}],
            },
        ) as resp:
            if resp.status != 200:
                return raw_text  # fallback to original
            data = await resp.json()
            refined = data.get("content", [{}])[0].get("text", "").strip()
            return refined if refined else raw_text


async def generate_reading(
    analysis: dict,
    anthropic_api_key: str,
    next_time: str,
    tipo: str = "lectura",
    lessons: list = None,
) -> str:
    now_et = datetime.now(ET)
    time_str = now_et.strftime("%I:%M %p")

    input_data = {
        "tipo": tipo,
        "ticker": analysis["ticker"],
        "price": int(analysis["price"]) if analysis["price"] else 0,
        "time": time_str,
        "next_time": next_time,
        "supports": [
            {
                "strike": int(s["strike"]),
                "dex_signal": s["dex_signal"],
                "gex_signal": s["gex_signal"],
                "es_precio": s["es_precio"],
            }
            for s in analysis.get("supports", [])[:3]
        ],
        "resistances": [
            {
                "strike": int(r["strike"]),
                "dex_signal": r["dex_signal"],
                "gex_signal": r["gex_signal"],
            }
            for r in analysis.get("resistances", [])[:2]
        ],
        "magnetic_zones": analysis.get("magnetic_zones", []),
    }

    criteria_text = criteria.get_active_prompt()
    criteria_section = f"\n\nAJUSTES DE CRITERIO DEL INSTRUCTOR (aplica siempre):\n{criteria_text}" if criteria_text else ""
    data_message = f"Genera el mensaje para estos datos:\n{json.dumps(input_data, indent=2)}{criteria_section}"

    # Build multimodal content — inject active lessons before market data
    content = []
    if lessons:
        content.append({
            "type": "text",
            "text": "LECCIONES APRENDIDAS DEL INSTRUCTOR — aplica este conocimiento en la lectura actual:\n",
        })
        for i, lesson in enumerate(lessons, 1):
            img_b64 = lesson.get("image_b64", "")
            if img_b64:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": lesson.get("image_type", "image/png"),
                        "data": img_b64,
                    },
                })
            rule = lesson.get("rule") or lesson.get("text", "")
            answer_ctx = f"\n  Contexto adicional: {lesson['answer']}" if lesson.get("answer") else ""
            summary_ctx = f"\n  Situacion: {lesson['summary']}" if lesson.get("summary") else ""
            content.append({
                "type": "text",
                "text": (
                    f"[Leccion {i} — {lesson.get('category', 'General')}]\n"
                    f"  Regla: {rule}{summary_ctx}{answer_ctx}\n"
                ),
            })
        content.append({"type": "text", "text": "---\nAhora genera la lectura:\n"})
    content.append({"type": "text", "text": data_message})

    user_message = content if lessons else data_message

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 600,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_message}],
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                print(f"[Claude] Error {resp.status}: {text[:400]}")
                return None
            data = await resp.json()
            if "content" not in data or not data["content"]:
                print(f"[Claude] Respuesta inesperada: {data}")
                return None
            text = data["content"][0]["text"]
            text = text.strip().strip("```").strip()
            return text
