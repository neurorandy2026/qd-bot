import aiohttp
import json
from datetime import datetime
from zoneinfo import ZoneInfo

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


async def generate_reading(
    analysis: dict,
    anthropic_api_key: str,
    next_time: str,
    tipo: str = "lectura",
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

    user_message = f"Genera el mensaje para estos datos:\n{json.dumps(input_data, indent=2)}"

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
                print(f"[Claude] Error: {resp.status} — {text[:200]}")
                return None
            data = await resp.json()
            text = data["content"][0]["text"]
            text = text.strip().strip("```").strip()
            return text
