"""
Applies Randy's DEX/GEX criteria to classify strikes and detect significant changes.

DEX (DELTA exposure, PER_ONE_PERCENT_MOVE, 0DTE):
  Positive (green) = retail bought PUTS → MM hedges by buying → supports price
  Negative (red)   = retail bought CALLS → MM hedges by selling → resists price

  SPY thresholds (baseline):
    1.5B–4B   → "preferido"  (preferred support/resistance)
    4B–10B    → "solido"     (solid support/resistance)
    >10B      → "cuidado"    (danger zone — large exposure, cascade risk if broken)
    Consecutive strikes >2.5B same sign → magnetic zone

  SPX thresholds: ×10 (SPX notional ~10× SPY per 1% move)

GEX (GAMMA exposure, PER_ONE_PERCENT_MOVE, 0DTE):
  >+800M  → "estable"    (MM long gamma, stabilizes price, calm movement)
  <-1B    → "rojo"       (MM short gamma, amplifies moves)
"""

from typing import Optional

# SPY baseline thresholds
DEX_PREFERRED_MIN = 1.5e9
DEX_PREFERRED_MAX = 4e9
DEX_SOLID_MAX     = 10e9
DEX_MAGNETIC_MIN  = 2.5e9
GEX_STABLE_MIN    = 800e6
GEX_RED_MAX       = -1e9
GEX_WALL_MIN      = 2e9

# Per-ticker geometry
_TICKER_SCALE   = {"SPX": 10.0, "SPY": 1.0, "QQQ": 1.0}
_STRIKE_RANGE   = {"SPX": 150,  "SPY": 20,  "QQQ": 15}   # points above/below price
_STRIKE_SPACING = {"SPX": 6.0,  "SPY": 1.5, "QQQ": 1.5}  # max gap for "consecutive"
_PRICE_PROX     = {"SPX": 3.0,  "SPY": 0.6, "QQQ": 0.6}  # window to tag es_precio
_GEX_NEAR_RANGE = {"SPX": 25,   "SPY": 5,   "QQQ": 5}    # points for gex_context calc


def _dex_signal(dex_net: float, scale: float = 1.0) -> Optional[str]:
    abs_val = abs(dex_net)
    if abs_val < DEX_PREFERRED_MIN * scale:
        return None
    if abs_val <= DEX_PREFERRED_MAX * scale:
        return "resistencia_preferida" if dex_net < 0 else "preferido"
    if abs_val <= DEX_SOLID_MAX * scale:
        return "resistencia_solida" if dex_net < 0 else "solido"
    return "resistencia_cuidado" if dex_net < 0 else "cuidado"


def _gex_signal(gex_net: float, scale: float = 1.0) -> Optional[str]:
    if gex_net >= GEX_STABLE_MIN * scale * 2:
        return "muy_estable"
    if gex_net >= GEX_STABLE_MIN * scale:
        return "estable"
    if gex_net <= GEX_RED_MAX * scale:
        return "rojo"
    return None


def _detect_magnetic_zones(sorted_levels: list, max_gap: float = 1.5,
                            magnetic_min: float = DEX_MAGNETIC_MIN) -> list:
    zones = []
    i = 0
    while i < len(sorted_levels):
        level = sorted_levels[i]
        dex = level["dex_net"]
        if abs(dex) >= magnetic_min:
            zone = [level]
            j = i + 1
            while j < len(sorted_levels):
                next_level = sorted_levels[j]
                if (sorted_levels[j]["strike"] - sorted_levels[j-1]["strike"] <= max_gap and
                        abs(next_level["dex_net"]) >= magnetic_min and
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


def _find_dex_flip(levels: list, price: float) -> Optional[dict]:
    """MVC: strike donde la exposición delta neta de los MMs cruza cero.
    Sobre el flip → MMs compran para cubrirse (soporte estructural).
    Bajo el flip  → MMs venden para cubrirse (presión bajista estructural).
    """
    sorted_levels = sorted(levels, key=lambda x: x["strike"])
    flips = []
    for i in range(len(sorted_levels) - 1):
        a = sorted_levels[i]
        b = sorted_levels[i + 1]
        if a["dex_net"] == 0 or b["dex_net"] == 0:
            continue
        if (a["dex_net"] > 0) != (b["dex_net"] > 0):
            flip_strike = round((a["strike"] + b["strike"]) / 2, 1)
            flips.append({
                "strike": flip_strike,
                "price_above_flip": price > flip_strike,
                "distance": flip_strike - price,
            })
    if not flips:
        return None
    return min(flips, key=lambda x: abs(x["distance"]))


def _find_gex_flip(levels: list, price: float) -> Optional[dict]:
    sorted_levels = sorted(levels, key=lambda x: x["strike"])
    flips = []
    for i in range(len(sorted_levels) - 1):
        a = sorted_levels[i]
        b = sorted_levels[i + 1]
        if a["gex_net"] == 0 or b["gex_net"] == 0:
            continue
        if (a["gex_net"] > 0) != (b["gex_net"] > 0):
            flip_strike = round((a["strike"] + b["strike"]) / 2, 1)
            flips.append({
                "strike": flip_strike,
                "price_above_flip": price > flip_strike,
                "distance": flip_strike - price,
            })
    if not flips:
        return None
    return min(flips, key=lambda x: abs(x["distance"]))


def _find_gex_walls(levels: list, price: float, wall_min: float = GEX_WALL_MIN) -> list:
    walls = []
    for level in levels:
        if level["gex_net"] >= wall_min:
            walls.append({
                "strike": level["strike"],
                "gex_b": round(level["gex_net"] / 1e9, 2),
                "side": "arriba" if level["strike"] > price else "abajo",
                "distance": round(level["strike"] - price, 1),
            })
    return sorted(walls, key=lambda x: abs(x["distance"]))[:3]


def _calculate_sesgo(levels: list, price: float,
                     scale: float = 1.0, gex_near_range: float = 5) -> dict:
    below = [l for l in levels if l["strike"] < price]
    above = [l for l in levels if l["strike"] > price]

    dex_support_total = sum(l["dex_net"] for l in below if l["dex_net"] > 0)
    dex_resist_total  = abs(sum(l["dex_net"] for l in above if l["dex_net"] < 0))

    near = [l for l in levels if abs(l["strike"] - price) <= gex_near_range]
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

    if gex_near > 2e9 * scale:
        gex_context = "GEX positivo cerca del precio — movimiento controlado"
    elif gex_near < -1e9 * scale:
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

    top_supports.sort(key=lambda x: x["strike"], reverse=True)
    top_resistances.sort(key=lambda x: x["strike"])

    return {
        "top_supports":    top_supports,
        "top_resistances": top_resistances,
    }


def analyze(market_data: dict) -> dict:
    price  = market_data["price"]
    dex_map = market_data["dex"]
    gex_map = market_data["gex"]
    ticker  = market_data.get("ticker", "SPY")

    if price is None:
        return {}

    scale       = _TICKER_SCALE.get(ticker, 1.0)
    strike_range = _STRIKE_RANGE.get(ticker, 20)
    max_gap     = _STRIKE_SPACING.get(ticker, 1.5)
    price_prox  = _PRICE_PROX.get(ticker, 0.6)
    gex_near_r  = _GEX_NEAR_RANGE.get(ticker, 5)

    all_strikes = sorted(set(list(dex_map.keys()) + list(gex_map.keys())),
                         key=lambda x: float(x))

    levels = []
    for s_str in all_strikes:
        s = float(s_str)
        if not (price - strike_range <= s <= price + strike_range):
            continue

        d = dex_map.get(s_str, {})
        g = gex_map.get(s_str, {})

        dex_net = d.get("callExposure", 0) + d.get("putExposure", 0)
        gex_net = g.get("callExposure", 0) + g.get("putExposure", 0)

        levels.append({
            "strike":     s,
            "dex_net":    dex_net,
            "gex_net":    gex_net,
            "dex_b":      round(dex_net / 1e9, 2),
            "gex_m":      round(gex_net / 1e6, 0),
            "dex_signal": _dex_signal(dex_net, scale),
            "gex_signal": _gex_signal(gex_net, scale),
            "es_precio":  abs(s - price) < price_prox,
        })

    magnetic_zones = _detect_magnetic_zones(
        levels,
        max_gap=max_gap,
        magnetic_min=DEX_MAGNETIC_MIN * scale,
    )

    supports    = [l for l in levels if l["dex_net"] > 0 and l["dex_signal"] and l["strike"] <= price + 1]
    resistances = [l for l in levels if l["dex_net"] < 0 and l["dex_signal"] and l["strike"] >= price - 1]

    supports.sort(key=lambda x: x["strike"], reverse=True)
    resistances.sort(key=lambda x: x["strike"])

    sesgo         = _calculate_sesgo(levels, price, scale=scale, gex_near_range=gex_near_r)
    zonas_fuertes = _rank_zonas_fuertes(supports, resistances, magnetic_zones)
    gex_flip      = _find_gex_flip(levels, price)
    dex_flip      = _find_dex_flip(levels, price)
    gex_walls     = _find_gex_walls(levels, price, wall_min=GEX_WALL_MIN * scale)

    return {
        "ticker":         ticker,
        "price":          price,
        "date":           market_data["date"],
        "levels":         levels,
        "supports":       supports[:5],
        "resistances":    resistances[:3],
        "magnetic_zones": magnetic_zones,
        "sesgo":          sesgo,
        "zonas_fuertes":  zonas_fuertes,
        "gex_flip":       gex_flip,
        "dex_flip":       dex_flip,
        "gex_walls":      gex_walls,
    }


def detect_significant_change(prev: dict, curr: dict) -> bool:
    if not prev or not curr:
        return True

    prev_price = prev.get("price", 0)
    curr_price = curr.get("price", 0)

    prev_supports = {s["strike"] for s in prev.get("supports", [])}
    for support in prev_supports:
        if prev_price >= support > curr_price:
            print(f"[Analyzer] Soporte {support} roto — alerta inmediata")
            return True

    prev_resistances = {r["strike"] for r in prev.get("resistances", [])}
    for resistance in prev_resistances:
        if prev_price <= resistance < curr_price:
            print(f"[Analyzer] Resistencia {resistance} rota — alerta inmediata")
            return True

    prev_zones = len(prev.get("magnetic_zones", []))
    curr_zones = len(curr.get("magnetic_zones", []))
    if curr_zones > prev_zones:
        print("[Analyzer] Nueva zona magnetica detectada — alerta inmediata")
        return True

    prev_cuidado = {s["strike"] for s in prev.get("supports", []) if s["dex_signal"] == "cuidado"}
    curr_cuidado = {s["strike"] for s in curr.get("supports", []) if s["dex_signal"] == "cuidado"}
    if curr_cuidado - prev_cuidado:
        print("[Analyzer] Nueva zona de cuidado — alerta inmediata")
        return True

    return False
