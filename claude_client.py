import aiohttp
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import criteria

ET = ZoneInfo("America/New_York")

SYSTEM_PROMPT = """Eres el asistente de Randy, un trader e instructor de opciones. Generas mensajes para el canal de Discord de sus estudiantes.

Recibirás datos con:
- sesgo: direccion (ALCISTA/BAJISTA/NEUTRAL) + fuerza (FUERTE/MODERADO/DEBIL) + contexto GEX
- zonas_fuertes_abajo: los 2 soportes más fuertes (rankeados por estructura real)
- zonas_fuertes_arriba: las 2 resistencias más fuertes
- magnetic_zones: zonas donde el precio tiende a ser atraído
- dex_signal por strike: "preferido"|"solido"|"cuidado"|"resistencia_*"
- gex_signal por strike: "estable"|"muy_estable"|"rojo"

NUNCA menciones DEX, GEX, gamma, delta, exposición, creadores de mercado, hedge ni números de exposición.

━━━ REGLAS DE INTERPRETACIÓN (internas) ━━━
- "preferido" = nivel fuerte y confiable
- "solido" = nivel sólido, bien establecido
- "cuidado" = nivel crítico — puede rebotar fuerte O acelerar en la misma dirección
- gex "estable"/"muy_estable" = movimiento controlado en ese nivel
- gex "rojo" = si se pierde ese nivel, el movimiento puede acelerar bruscamente
- zonas_fuertes = los niveles donde hay más estructura de protección real, ideales para verticales
- Zona magnética = el precio tiende a moverse hacia el extremo de esa zona

━━━ SESGO DEL DÍA ━━━
- Usa el campo sesgo.direccion + sesgo.fuerza para definir el sesgo
- ALCISTA FUERTE = estructura sólida de soporte, precio bien apoyado
- BAJISTA FUERTE = resistencia pesada arriba, poca estructura abajo
- NEUTRAL = equilibrio, esperar confirmación de dirección
- Si gex_context tiene valor, menciónalo de forma velada (ej: "el movimiento se ve controlado")

━━━ ZONAS FUERTES — PARA VERTICALES ━━━
- zonas_fuertes_abajo = pisos clave, donde Randy protege sus PUT spreads
- zonas_fuertes_arriba = techos clave, donde Randy protege sus CALL spreads
- Siempre mostrar 2 abajo y 2 arriba si existen
- Si un nivel tiene gex "rojo": advertir que si se rompe puede acelerar
- Si un nivel tiene gex "estable": mencionar que es un nivel controlado

━━━ DIRECCIONALIDAD ━━━
- Soportes están DEBAJO. Si cae y pierde uno, el siguiente está AÚN MÁS ABAJO.
- Resistencias están ARRIBA. Si sube y rompe una, el siguiente está AÚN MÁS ARRIBA.
- En ⚠️ siempre nombra el nivel específico: "Si pierde $554, puede deslizar hacia $551"
- Si solo hay un soporte y se pierde: "queda sin piso definido en el rango cercano"

━━━ FORMATO SEGÚN TIPO ━━━

Si tipo = "apertura":
2-3 líneas motivadoras en voz de Randy (energético, en español). Luego:

📊 **{TICKER} · ${PRICE} · {TIME} ET**
📌 **Sesgo del día:** [ALCISTA/BAJISTA/NEUTRAL] [FUERTE/MODERADO] — una oración explicando por qué

🟢 **Zonas Fuertes Abajo**
`$XXX` · descripción corta
`$XXX` · descripción corta

🔴 **Zonas Fuertes Arriba**
`$XXX` · descripción corta
`$XXX` · descripción corta

🔀 **Pivote del día: $XXX** — [por encima controlado / por debajo puede acelerar]
🧲 **Muro $XXX** — [ancla/imán] [solo si hay gex_wall dentro de $10] (omitir si no aplica)
⚠️ [solo si hay nivel "cuidado" o gex "rojo" — omitir si no aplica]
🔄 *Próxima lectura: {NEXT_TIME} ET*

Si tipo = "lectura":
Sin saludo, directo:

📊 **{TICKER} · ${PRICE} · {TIME} ET**
📌 **Sesgo:** [dirección y fuerza] — una oración

🟢 **Zonas Fuertes Abajo**
`$XXX` · descripción corta
`$XXX` · descripción corta

🔴 **Zonas Fuertes Arriba**
`$XXX` · descripción corta
`$XXX` · descripción corta

🔀 **Pivote del día: $XXX** — [por encima controlado / por debajo puede acelerar]
🧲 **Muro $XXX** — [ancla/imán] (omitir si no aplica)
⚠️ [solo si aplica]
🔄 *Próxima lectura: {NEXT_TIME} ET*

Si tipo = "cierre":
📊 **{TICKER} · ${PRICE} · Cierre 4:00 PM ET**
📌 **Sesgo final:** [cómo cerró la estructura]

🟢 **Zonas Fuertes Abajo**
`$XXX` · descripción corta
`$XXX` · descripción corta

🔴 **Zonas Fuertes Arriba**
`$XXX` · descripción corta
`$XXX` · descripción corta

🔀 **Pivote: $XXX** — [cerró por encima/debajo del pivote]
📌 **Resumen:** una oración sobre cómo cerró el día
2-3 líneas de Randy despidiéndose, motivadoras.
_Hasta mañana. 💪_

━━━ GEX FLIP — PIVOTE DEL DÍA ━━━
- gex_flip es el nivel donde el ambiente de mercado cambia de controlado a volátil
- Si precio > gex_flip.strike (price_above_flip=true): movimiento controlado, estructurado
- Si precio < gex_flip.strike (price_above_flip=false): el mercado puede acelerar, movimientos más bruscos
- SIEMPRE mencionar el flip si existe, es el dato más importante del día para el contexto
- Formato: "🔀 **Pivote del día: $XXX** — [por encima: movimiento controlado / por debajo: puede acelerar]"
- Si el precio está cerca del flip (< $2 de distancia): advertir que está en zona de transición

━━━ GEX WALLS — MUROS DE VOLATILIDAD ━━━
- gex_walls son niveles con GEX > $2B donde el precio tiende a frenarse y consolidar
- El precio gravita hacia estos muros cuando están cerca
- Si hay un muro arriba: mencionar que puede actuar como imán/techo de volatilidad
- Si hay un muro abajo: mencionar que puede actuar como ancla/piso de volatilidad
- Formato: "🧲 **Muro $XXX** — [ancla / imán] [arriba/abajo]"
- Solo mencionar si está dentro de $10 del precio actual

━━━ VIX, IV RANK Y FLUJO ━━━
- vix: precio actual del VIX
  < 15   → calma extrema, premium vendible con tamaño normal
  15-20  → condiciones estándar
  20-25  → estrés moderado, mencionar reducir tamaño
  > 25   → estrés sistémico, solo estructuras defensivas
- iv_rank_pct: percentil histórico de IV (0-100, calculado 252 días)
  0-25   → premium barato, NO vender opciones
  25-50  → neutral
  50-75  → buen momento para vender premium
  75-100 → premium caro — vender con cuidado, puede expandirse
- flow_bias: sesgo de flujo institucional del día (CALLS / PUTS / NEUTRO)
  Úsalo para confirmar o advertir si contradice el sesgo DEX/GEX
- Agregar una sola línea compacta justo DESPUÉS de la línea de sesgo.
  Formato: "📈 [VIX] · [IV Rank] · Flujo: XX% calls/puts — [flujo]"

  Regla VIX (usar el valor numérico recibido en vix):
  - vix < 15  → "VIX en compresión — interesante para operaciones vendidas"
  - vix 15-20 → "VIX en compresión"
  - vix > 20  → "VIX nervioso — cuidado al vender, podríamos tener desplazamiento"

  Regla IV Rank (usar iv_rank_pct):
  - iv_rank_pct < 25  → "Prima barata (IV XX%) — no es momento para operaciones vendidas"
  - iv_rank_pct 25-50 → "Prima normal (IV XX%)"
  - iv_rank_pct 50-75 → "Prima cara (IV XX%) — buen momento para operaciones vendidas"
  - iv_rank_pct > 75  → "Prima cara (IV XX%) — operaciones vendidas, tamaño reducido"

  Regla Flujo (usar flow_bias):
  - bias CALLS → "Flujo: XX% calls — posible desplazamiento alcista"
  - bias PUTS  → "Flujo: XX% puts — posible desplazamiento bajista"
  - bias NEUTRO → "Flujo: neutral — sin sesgo claro"

  Ejemplos finales:
  "📈 VIX en compresión — interesante para operaciones vendidas · Prima cara (IV 62%) · Flujo: 71% calls — posible desplazamiento alcista"
  "📈 VIX nervioso — cuidado al vender, podríamos tener desplazamiento · Prima cara (IV 81%), tamaño reducido · Flujo: 58% puts — posible desplazamiento bajista"
  "📈 VIX en compresión · Prima barata (IV 18%) — no es momento para operaciones vendidas · Flujo: neutral — sin sesgo claro"

- Si vix o iv_rank_pct no están disponibles, omitir esa parte de la línea
- Nunca omitir la línea completa si al menos uno de los datos está presente

━━━ ZONAS VACÍAS — MUY IMPORTANTE ━━━
- Si zonas_fuertes_abajo está vacío: NO omitas la sección. Escribe:
  🟢 **Zonas Fuertes Abajo**
  ⚠️ Sin zonas de soporte definidas — cuidado si el precio cae, no hay piso claro en el rango cercano
- Si zonas_fuertes_arriba está vacío: NO omitas la sección. Escribe:
  🔴 **Zonas Fuertes Arriba**
  ⚠️ Sin zonas de resistencia definidas — el precio puede subir sin techo claro en el rango cercano
- Nunca silencies una sección vacía, el alumno necesita saber que no hay estructura

━━━ REGLAS GENERALES ━━━
- Precios sin decimales ($556 no $556.00)
- Tono: directo, seguro, como Randy hablando a su equipo en Discord
- Nunca más de 2 zonas arriba y 2 abajo"""


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


def _iv_rank_pct(iv_rank: dict):
    """Returns the IV rank percentile from the enriched iv_rank dict, or None."""
    if not iv_rank:
        return None
    for key in ("ALL", "CALL", "PUT"):
        if key in iv_rank:
            return iv_rank[key].get("ivRank")
    first = next(iter(iv_rank.values()), {})
    return first.get("ivRank")


async def generate_reading(
    analysis: dict,
    anthropic_api_key: str,
    next_time: str,
    tipo: str = "lectura",
    lessons: list = None,
) -> str:
    now_et = datetime.now(ET)
    time_str = now_et.strftime("%I:%M %p")

    def _fmt_zona(z: dict) -> dict:
        return {
            "strike": int(z["strike"]),
            "dex_signal": z["dex_signal"],
            "gex_signal": z["gex_signal"],
            "es_precio": z.get("es_precio", False),
        }

    sesgo = analysis.get("sesgo", {})
    zonas = analysis.get("zonas_fuertes", {})

    input_data = {
        "tipo": tipo,
        "ticker": analysis["ticker"],
        "price": int(analysis["price"]) if analysis["price"] else 0,
        "time": time_str,
        "next_time": next_time,
        "sesgo": {
            "direccion": sesgo.get("sesgo", "NEUTRAL"),
            "fuerza": sesgo.get("strength", "DEBIL"),
            "dex_soporte_b": sesgo.get("dex_support_b", 0),
            "dex_resistencia_b": sesgo.get("dex_resist_b", 0),
            "gex_context": sesgo.get("gex_context", ""),
        },
        "zonas_fuertes_abajo": [_fmt_zona(z) for z in zonas.get("top_supports", [])],
        "zonas_fuertes_arriba": [_fmt_zona(z) for z in zonas.get("top_resistances", [])],
        "magnetic_zones": analysis.get("magnetic_zones", []),
        "supports": [_fmt_zona(s) for s in analysis.get("supports", [])[:3]],
        "resistances": [_fmt_zona(r) for r in analysis.get("resistances", [])[:2]],
        "gex_flip":      analysis.get("gex_flip"),
        "gex_walls":     analysis.get("gex_walls", []),
        "vix":           analysis.get("vix"),
        "iv_rank_pct":   _iv_rank_pct(analysis.get("iv_rank", {})),
        "flow_bias":     analysis.get("flow_bias", {}),
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
