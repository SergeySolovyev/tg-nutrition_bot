import asyncio
import difflib
import re
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from config import OPENWEATHER_API_KEY


# -----------------------------
# Weather
# -----------------------------


async def get_city_temperature_c(city: str) -> Optional[float]:
    """Получить текущую температуру в городе (°C).

    Если задан OPENWEATHER_API_KEY → используем OpenWeatherMap.
    Иначе → используем бесплатный Open-Meteo (без ключа).
    """
    city = (city or "").strip()
    if not city:
        return None

    # 1) OpenWeatherMap
    if OPENWEATHER_API_KEY:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric"}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, timeout=15) as r:
                    if r.status != 200:
                        return None
                    data = await r.json()
                    main = data.get("main") or {}
                    t = main.get("temp")
                    return float(t) if t is not None else None
            except aiohttp.ClientError:
                return None
            except asyncio.TimeoutError:
                return None

    # 2) Fallback: Open-Meteo (no key)
    async with aiohttp.ClientSession() as session:
        try:
            # geocoding
            geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
            async with session.get(
                geocode_url,
                params={"name": city, "count": 1, "language": "ru", "format": "json"},
                timeout=15,
            ) as r:
                if r.status != 200:
                    return None
                geo = await r.json()
                results = geo.get("results") or []
                if not results:
                    return None
                lat = results[0].get("latitude")
                lon = results[0].get("longitude")
                if lat is None or lon is None:
                    return None

            # weather
            forecast_url = "https://api.open-meteo.com/v1/forecast"
            async with session.get(
                forecast_url,
                params={"latitude": lat, "longitude": lon, "current_weather": True},
                timeout=15,
            ) as r:
                if r.status != 200:
                    return None
                w = await r.json()
                cw = w.get("current_weather") or {}
                t = cw.get("temperature")
                return float(t) if t is not None else None
        except aiohttp.ClientError:
            return None
        except asyncio.TimeoutError:
            return None


# -----------------------------
# Food parsing & OpenFoodFacts
# -----------------------------


STOP_WORDS = {
    "без",
    "с",
    "и",
    "или",
    "на",
    "в",
    "по",
    "из",
    "для",
    "со",
    "упаковка",
    "пачка",
    "пакет",
    "шт",
    "штуки",
    "штук",
}


def normalize_food_name(text: str) -> str:
    t = (text or "").lower().strip()
    t = t.replace("ё", "е")
    t = re.sub(r"\([^)]*\)", " ", t)  # remove parenthesis
    t = re.sub(r"[^0-9a-zа-я\s]+", " ", t)
    parts = [p for p in t.split() if p and p not in STOP_WORDS]
    return " ".join(parts)


def parse_amount_suffix(raw: str) -> Tuple[Optional[float], Optional[str]]:
    """Parse amount like '250', '250g', '250гр', '250 мл', '2шт', '1 порция'.

    Returns (value, unit) where unit in {'g','ml','piece','serving','auto'}.
    'auto' used when user put just a small number (<=10) with no unit.
    """
    s = (raw or "").strip().lower()
    s = s.replace(",", ".")

    # common patterns: "250ml", "250 мл", "2шт", "1 порция"
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(г|гр|g|gram|grams)$", s)
    if m:
        return float(m.group(1)), "g"

    m = re.match(r"^(\d+(?:\.\d+)?)\s*(мл|ml)$", s)
    if m:
        return float(m.group(1)), "ml"

    m = re.match(r"^(\d+(?:\.\d+)?)\s*(шт|pcs|piece|pieces)$", s)
    if m:
        return float(m.group(1)), "piece"

    m = re.match(r"^(\d+(?:\.\d+)?)\s*(порц|порция|порции|serving|portion)$", s)
    if m:
        return float(m.group(1)), "serving"

    m = re.match(r"^(\d+(?:\.\d+)?)$", s)
    if m:
        val = float(m.group(1))
        if val <= 10:
            return val, "auto"  # likely pieces
        return val, "g"  # likely grams

    return None, None


def split_food_and_amount(args: str) -> Tuple[str, Optional[float], Optional[str]]:
    """Split '/log_food <food> [amount]' into food query + optional amount."""
    text = (args or "").strip()
    if not text:
        return "", None, None

    parts = text.split()
    if len(parts) >= 2:
        # try parse last token as amount
        val, unit = parse_amount_suffix(parts[-1])
        if val is not None and unit is not None:
            food = " ".join(parts[:-1]).strip()
            return food, val, unit

        # try parse last TWO tokens like "250 мл" or "2 шт"
        tail = " ".join(parts[-2:])
        val, unit = parse_amount_suffix(tail)
        if val is not None and unit is not None:
            food = " ".join(parts[:-2]).strip()
            return food, val, unit

    return text, None, None


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def kcal_from_nutriments(nutr: Dict[str, Any]) -> Optional[float]:
    """Return kcal/100g from nutriments.

    Supports:
    - energy-kcal_100g
    - energy-kj_100g / energy_100g (usually kJ)
    - Atwater from macros: proteins_100g, fat_100g, carbohydrates_100g
    """
    if not nutr:
        return None

    kcal = _to_float(nutr.get("energy-kcal_100g"))
    if kcal is not None and kcal > 0:
        return kcal

    # sometimes energy_100g is kJ
    kj = _to_float(nutr.get("energy-kj_100g"))
    if kj is None:
        kj = _to_float(nutr.get("energy_100g"))
    if kj is not None and kj > 0:
        return kj / 4.184

    # Atwater: 4-9-4
    p = _to_float(nutr.get("proteins_100g"))
    f = _to_float(nutr.get("fat_100g"))
    c = _to_float(nutr.get("carbohydrates_100g"))
    if p is not None and f is not None and c is not None:
        est = 4.0 * p + 9.0 * f + 4.0 * c
        if est > 0:
            return est

    return None


def parse_serving_g(serving_size: Any) -> Optional[float]:
    """Parse serving_size like '30 g', '250ml', '1 bar (40g)' etc."""
    if not serving_size:
        return None
    s = str(serving_size).lower().strip()
    s = s.replace(",", ".")

    # first try a simple '40g' or '40 g'
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|гр|г)\b", s)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None

    # if ml: assume density 1 => g
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|мл)\b", s)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None

    return None


def match_score(query_norm: str, name_norm: str) -> int:
    if not query_norm or not name_norm:
        return 0
    return int(round(difflib.SequenceMatcher(a=query_norm, b=name_norm).ratio() * 100))


def weighted_median(values: List[float], weights: List[float]) -> float:
    pairs = sorted(zip(values, weights), key=lambda x: x[0])
    total = sum(weights)
    if total <= 0:
        return statistics.median(values)
    cum = 0.0
    for v, w in pairs:
        cum += w
        if cum >= 0.5 * total:
            return v
    return pairs[-1][0]


@dataclass
class FoodOption:
    name: str
    kcal_100g: float
    score: int
    source: str
    serving_g: Optional[float] = None


async def search_openfoodfacts_candidates(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    url = "https://world.openfoodfacts.org/cgi/search.pl"
    params = {
        "action": "process",
        "search_terms": q,
        "json": "true",
        "page_size": max(1, min(int(limit), 25)),
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=15) as r:
                if r.status != 200:
                    return []
                data = await r.json()
        except aiohttp.ClientError:
            return []
        except asyncio.TimeoutError:
            return []

    return data.get("products") or []


async def food_by_barcode(barcode: str) -> Optional[FoodOption]:
    bc = re.sub(r"\D+", "", barcode or "")
    if not bc:
        return None

    url = f"https://world.openfoodfacts.org/api/v0/product/{bc}.json"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=15) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        except aiohttp.ClientError:
            return None
        except asyncio.TimeoutError:
            return None

    if not data or data.get("status") != 1:
        return None

    p = data.get("product") or {}
    name = p.get("product_name") or p.get("generic_name") or "Неизвестно"
    nutr = p.get("nutriments") or {}
    kcal = kcal_from_nutriments(nutr)
    if kcal is None:
        return None
    serving_g = parse_serving_g(p.get("serving_size"))
    return FoodOption(name=str(name), kcal_100g=float(kcal), score=100, source="barcode", serving_g=serving_g)


def best_custom_match(query: str, custom_foods: Dict[str, Any]) -> Optional[FoodOption]:
    qn = normalize_food_name(query)
    if not qn or not custom_foods:
        return None

    # exact
    if qn in custom_foods:
        rec = custom_foods[qn] or {}
        kcal = _to_float(rec.get("kcal_100g"))
        if kcal is None:
            return None
        serving_g = _to_float(rec.get("serving_g"))
        display = rec.get("name") or rec.get("display_name") or query
        return FoodOption(name=str(display), kcal_100g=float(kcal), score=100, source="custom_exact", serving_g=serving_g)

    # fuzzy
    best: Optional[Tuple[str, int]] = None
    for k in custom_foods.keys():
        s = match_score(qn, str(k))
        if best is None or s > best[1]:
            best = (str(k), s)

    if not best:
        return None
    key, sc = best
    if sc < 70:
        return None

    rec = custom_foods.get(key) or {}
    kcal = _to_float(rec.get("kcal_100g"))
    if kcal is None:
        return None
    serving_g = _to_float(rec.get("serving_g"))
    display = rec.get("name") or rec.get("display_name") or key
    return FoodOption(name=str(display), kcal_100g=float(kcal), score=int(sc), source="custom_fuzzy", serving_g=serving_g)


async def estimate_food_option(
    query: str,
    custom_foods: Dict[str, Any],
    limit: int = 10,
) -> Dict[str, Any]:
    """Return dict with:

    - status: 'ok' | 'choose' | 'manual'
    - chosen: FoodOption | None
    - options: List[FoodOption]
    - confidence: int
    - note: str
    """
    raw = (query or "").strip()
    if not raw:
        return {"status": "manual", "chosen": None, "options": [], "confidence": 0, "note": "empty"}

    # barcode shortcut
    if re.fullmatch(r"\d{8,14}", raw.replace(" ", "")):
        opt = await food_by_barcode(raw)
        if opt:
            return {"status": "ok", "chosen": opt, "options": [opt], "confidence": 100, "note": "barcode"}

    # 1) custom
    c = best_custom_match(raw, custom_foods)
    if c:
        if c.source == "custom_exact" or c.score >= 85:
            conf = 95 if c.source == "custom_exact" else min(90, c.score)
            return {"status": "ok", "chosen": c, "options": [c], "confidence": int(conf), "note": c.source}
        # fuzzy but not super-high => ask
        return {
            "status": "choose",
            "chosen": None,
            "options": [c],
            "confidence": int(c.score),
            "note": "custom_fuzzy_low",
        }

    # 2) OpenFoodFacts candidates
    qn = normalize_food_name(raw)
    prods = await search_openfoodfacts_candidates(raw, limit=limit)
    options: List[FoodOption] = []
    for p in prods:
        if not p:
            continue
        name = p.get("product_name") or p.get("generic_name") or "Неизвестно"
        nutr = p.get("nutriments") or {}
        kcal = kcal_from_nutriments(nutr)
        if kcal is None:
            continue

        sn = normalize_food_name(str(name))
        sc = match_score(qn, sn)
        serving_g = parse_serving_g(p.get("serving_size"))
        options.append(FoodOption(name=str(name), kcal_100g=float(kcal), score=int(sc), source="off", serving_g=serving_g))

    if not options:
        return {"status": "manual", "chosen": None, "options": [], "confidence": 0, "note": "off_empty"}

    # sort by match
    options.sort(key=lambda x: x.score, reverse=True)
    top = options[: min(5, len(options))]

    # robust kcal estimate
    kcal_vals = [o.kcal_100g for o in top if 0 < o.kcal_100g < 900]
    weights = [max(1.0, o.score) for o in top if 0 < o.kcal_100g < 900]

    best = top[0]

    # confidence heuristic
    best_score = best.score
    second_score = top[1].score if len(top) > 1 else 0
    spread = best_score - second_score

    conf = 40
    if best_score >= 90:
        conf = 85
    elif best_score >= 80:
        conf = 75
    elif best_score >= 70:
        conf = 60

    if spread >= 10:
        conf += 5
    if len(kcal_vals) >= 3:
        conf += 5
    conf = max(0, min(95, conf))

    # pick robust kcal if enough evidence; otherwise use best
    if len(kcal_vals) >= 3:
        robust = weighted_median(kcal_vals, weights)
        chosen = FoodOption(
            name=best.name,
            kcal_100g=float(robust),
            score=best.score,
            source="off_robust",
            serving_g=best.serving_g,
        )
    else:
        chosen = FoodOption(
            name=best.name,
            kcal_100g=float(best.kcal_100g),
            score=best.score,
            source="off_best",
            serving_g=best.serving_g,
        )

    # if low confidence: let user choose among top 3
    if conf < 75:
        return {
            "status": "choose",
            "chosen": None,
            "options": options[:3],
            "confidence": int(conf),
            "note": "off_low_confidence",
        }

    return {
        "status": "ok",
        "chosen": chosen,
        "options": options[:3],
        "confidence": int(conf),
        "note": chosen.source,
    }


# Backward-compatible helper
async def search_openfoodfacts(product_name: str) -> Optional[Tuple[str, float]]:
    res = await estimate_food_option(product_name, custom_foods={}, limit=5)
    if res.get("status") == "ok" and res.get("chosen"):
        opt: FoodOption = res["chosen"]
        return opt.name, float(opt.kcal_100g)
    # fallback: old behavior
    prods = await search_openfoodfacts_candidates(product_name, limit=1)
    if not prods:
        return None
    p = prods[0] or {}
    name = p.get("product_name") or p.get("generic_name") or "Неизвестно"
    nutr = p.get("nutriments") or {}
    kcal = kcal_from_nutriments(nutr) or 0.0
    return str(name), float(kcal)


# Backward-compatible fuzzy_match_food
def fuzzy_match_food(product_name: str, custom_foods: dict, threshold: float = 0.6) -> Optional[Tuple[str, float]]:
    """Найти похожий продукт в кастомном словаре через fuzzy-match.
    
    Возвращает (название, ккал/100г) если найдено похожее совпадение.
    """
    opt = best_custom_match(product_name, custom_foods)
    if opt and opt.score >= int(threshold * 100):
        return opt.name, opt.kcal_100g
    return None
