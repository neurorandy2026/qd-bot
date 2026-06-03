"""
Applies Randy's DEX/GEX criteria to classify strikes and detect significant changes.

DEX (DELTA exposure, PER_ONE_PERCENT_MOVE, 0DTE):
  Positive (green) = retail bought PUTS → MM hedges by buying → supports price
  Negative (red)   = retail bought CALLS → MM hedges by selling → resists price

  2B–4B   → "preferido"  (preferred support/resistance)
  4B–10B  → "solido"     (solid support/resistance)
  >10B    → "cuidado"    (danger zone — large exposure, cascade risk if broken)
  Consecutive strikes >2.5B same sign → magnetic zone (MM pushes price through)

GEX (GAMMA exposure, PER_ONE_PERCENT_MOVE, 0DTE):
  >+800M  → "estable"    (MM long gamma, stabilizes price, calm movement)
  <-1B    → "rojo"       (MM short gamma, amplifies moves — freno o acelerador)
"""

from typing import Optional

DEX_PREFERRED_MIN = 2e9
DEX_PREFERRED_MAX = 4e9
DEX_SOLID_MAX = 10e9
DEX_MAGNETIC_MIN = 2.5e9
GEX_STABLE_MIN = 800e6
GEX_RED_MAX = -1e9
STRIKE_RANGE = 20  # strikes to analyze around current price


def _dex_signal(dex_net: float) -> Optional[str]:
    abs_val = abs(dex_net)
    if abs_val < DEX_PREFERRED_MIN:
        return None
    side = "resistencia" if dex_net < 0 else ""
    if abs_val <= DEX_PREFERRED_MAX:
        return f"resistencia_preferida" if dex_net < 0 else "preferido"
    if abs_val <= DEX_SOLID_MAX:
        return "resistencia_solida" if dex_net < 0 else "solido"
    return "resistencia_cuidado" if dex_net < 0 else "cuidado"


def _gex_signal(gex_net: float) -> Optional[str]:
    if gex_net >= GEX_STABLE_MIN:
        return "estable"
    if gex_net >= GEX_STABLE_MIN * 2:
        return "muy_estable"
    if gex_net <= GEX_RED_MAX:
        return "rojo"
    return None


def _detect_magnetic_zones(sorted_levels: list) -> list:
    """
    Find consecutive strikes where abs(dex_net) > DEX_MAGNETIC_MIN and same sign.
    Returns list of zones: {"strikes": [...], "direction": "alcista"|"bajista", "target": strike}
    """
    zones = []
    i = 0
    while i < len(sorted_levels):
        level = sorted_levels[i]
        dex = level["dex_net"]
        if abs(dex) >= DEX_MAGNETIC_MIN:
            zone = [level]
            j = i + 1
            while j < len(sorted_levels):
                next_level = sorted_levels[j]
                # Must be consecutive strike (within 1 point) and same direction
                if (sorted_levels[j]["strike"] - sorted_levels[j-1]["strike"] <= 1.5 and
                        abs(next_level["dex_net"]) >= DEX_MAGNETIC_MIN and
                        (next_level["dex_net"] > 0) == (dex > 0)):
                    zone.append(next_level)
                    j += 1
                else:
                    break
            if len(zone) >= 2:
                direction = "alcista" if dex > 0 else "bajista"
                target = zone[-1]["strike"] if direction == "alcista" else zone[0]["strike"]
                zones.append({
                    "strikes": [z["strike"] for z in zone],
                    "direction": direction,
                    "target": target,
                })
                i = j
                continue
        i += 1
    return zones


def _calculate_sesgo(levels: list, price: float) -> dict:
    """
    Calculates directional bias from DEX/GEX structure.

    Logic:
    - DEX balance: total positive DEX below price vs total negative DEX above
    - GEX near price: positive = controlled move, negative = can accelerate
    - Ratio >= 1.5 → ALCISTA, <= 0.67 → BAJISTA, else NEUTRAL
    """
    below = [l for l in levels if l["strike"] < price]
    above = [l for l in levels if l["strike"] > price]

    dex_support_total  = sum(l["dex_net"] for l in below if l["dex_net"] > 0)
    dex_resist_total   = abs(sum(l["dex_net"] for l in above if l["dex_net"] < 0))

    # GEX within 5 strikes of price
    near = [l for l in levels if abs(l["strike"] - price) <= 5]
    gex_near = sum(l["gex_net"] for l in near)

    ratio = dex_support_total / max(dex_resist_total, 1e8)

    if ratio >= 1.5:
        sesgo = "ALCISTA"
    elif ratio <= 0.67:
        sesgo = "BAJISTA"
    else:
        sesgo = "NEUTRAL"

    diff = abs(ratio - 1.0)
    strength = "FUERTE" if diff >= 0.8 else "MODERADO" if diff >= 0.35 else "DEBIL"

    if gex_near > 2e9:
        gex_context = "GEX positivo cerca del precio — movimiento controlado"
    elif gex_near < -1e9:
        gex_context = "GEX negativo cerca del precio — movimiento puede acelerar"
    else:
        gex_context = ""

    return {
        "sesgo": sesgo,
        "strength": strength,
        "dex_support_b": round(dex_support_total / 1e9, 1),
        "dex_resist_b": round(dex_resist_total / 1e9, 1),
        "gex_context": gex_context,
    }


def _rank_zonas_fuertes(supports: list, resistances: list, magnetic_zones: list) -> dict:
    """
    Ranks supports and resistances by composite strength score.
    Returns top 2 of each — Randy uses these for vertical spread protection.

    Score factors:
    - DEX magnitude (base)
    - GEX stable (+30%) → zone is held with controlled movement
    - GEX red    (-15%) → zone may not hold if broken
    - Magnetic zone (+40%) → MM actively pushes price to this level
    - cuidado signal (+10%) → very large DEX, MM must defend
    """
    magnetic_strikes = {s for z in magnetic_zones for s in z["strikes"]}

    def score(level: dict) -> float:
        base = abs(level["dex_net"])
        gex = level.get("gex_signal")
        if gex in ("estable", "muy_estable"):
            base *= 1.30
        elif gex == "rojo":
            base *= 0.85
        if level["strike"] in magnetic_strikes:
            base *= 1.40
        if level.get("dex_signal") in ("cuidado", "resistencia_cuidado"):
            base *= 1.10
        return base

    top_supports    = sorted(supports,    key=score, reverse=True)[:2]
    top_resistances = sorted(resistances, key=score, reverse=True)[:2]

    # Re-sort by strike for display (closest first)
    top_supports.sort(key=lambda x: x["strike"], reverse=True)
    top_resistances.sort(key=lambda x: x["strike"])

    return {
        "top_supports":    top_supports,
        "top_resistances": top_resistances,
    }


def analyze(market_data: dict) -> dict:
    """
    Takes raw market data and returns classified analysis.
    """
    price = market_data["price"]
    dex_map = market_data["dex"]
    gex_map = market_data["gex"]

    if price is None:
        return {}

    all_strikes = sorted(set(list(dex_map.keys()) + list(gex_map.keys())), key=lambda x: float(x))

    levels = []
    for s_str in all_strikes:
        s = float(s_str)
        if not (price - STRIKE_RANGE <= s <= price + STRIKE_RANGE):
            continue

        d = dex_map.get(s_str, {})
        g = gex_map.get(s_str, {})

        dex_net = d.get("callExposure", 0) + d.get("putExposure", 0)
        gex_net = g.get("callExposure", 0) + g.get("putExposure", 0)

        levels.append({
            "strike": s,
            "dex_net": dex_net,
            "gex_net": gex_net,
            "dex_b": round(dex_net / 1e9, 2),
            "gex_m": round(gex_net / 1e6, 0),
            "dex_signal": _dex_signal(dex_net),
            "gex_signal": _gex_signal(gex_net),
            "es_precio": abs(s - price) < 0.6,
        })

    magnetic_zones = _detect_magnetic_zones(levels)

    # Separate supports (green DEX, below or at price) and resistances (red DEX, above price)
    supports = [l for l in levels if l["dex_net"] > 0 and l["dex_signal"] and l["strike"] <= price + 1]
    resistances = [l for l in levels if l["dex_net"] < 0 and l["dex_signal"] and l["strike"] >= price - 1]

    supports.sort(key=lambda x: x["strike"], reverse=True)    # closest first going down
    resistances.sort(key=lambda x: x["strike"])               # closest first going up

    sesgo       = _calculate_sesgo(levels, price)
    zonas_fuertes = _rank_zonas_fuertes(supports, resistances, magnetic_zones)

    return {
        "ticker": market_data["ticker"],
        "price": price,
        "date": market_data["date"],
        "levels": levels,
        "supports": supports[:5],
        "resistances": resistances[:3],
        "magnetic_zones": magnetic_zones,
        "sesgo": sesgo,
        "zonas_fuertes": zonas_fuertes,
    }


def detect_significant_change(prev: dict, curr: dict) -> bool:
    """
    Returns True if something meaningful changed vs the previous analysis.
    Triggers an immediate Discord post.
    """
    if not prev or not curr:
        return True

    prev_price = prev.get("price", 0)
    curr_price = curr.get("price", 0)

    # Price crossed a key support level
    prev_supports = {s["strike"] for s in prev.get("supports", [])}
    for support in prev_supports:
        if prev_price >= support > curr_price:
            print(f"[Analyzer] Soporte {support} roto — alerta inmediata")
            return True

    # Price crossed a key resistance level
    prev_resistances = {r["strike"] for r in prev.get("resistances", [])}
    for resistance in prev_resistances:
        if prev_price <= resistance < curr_price:
            print(f"[Analyzer] Resistencia {resistance} rota — alerta inmediata")
            return True

    # New magnetic zone appeared
    prev_zones = len(prev.get("magnetic_zones", []))
    curr_zones = len(curr.get("magnetic_zones", []))
    if curr_zones > prev_zones:
        print("[Analyzer] Nueva zona magnetica detectada — alerta inmediata")
        return True

    # A new cuidado level appeared near price
    prev_cuidado = {s["strike"] for s in prev.get("supports", []) if s["dex_signal"] == "cuidado"}
    curr_cuidado = {s["strike"] for s in curr.get("supports", []) if s["dex_signal"] == "cuidado"}
    if curr_cuidado - prev_cuidado:
        print("[Analyzer] Nueva zona de cuidado — alerta inmediata")
        return True

    return False
