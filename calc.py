from dataclasses import dataclass
from typing import Optional


@dataclass
class Goals:
    water_ml: int
    calories: int


def calc_water_goal_ml(weight_kg: float, activity_min: int, temperature_c: Optional[float]) -> int:
    # Base: weight * 30 ml
    base = weight_kg * 30.0

    # +500 ml per each full 30 minutes of daily activity (discrete calculation)
    # Например: 45 минут = 1 полный блок 30 минут = +500 мл
    full_30min_blocks = activity_min // 30
    extra_activity = full_30min_blocks * 500.0

    # Hot weather bonus
    extra_heat = 0.0
    if temperature_c is not None and temperature_c > 25:
        # simple rule: 25-30 => +500, >30 => +1000
        extra_heat = 500.0 if temperature_c <= 30 else 1000.0

    return int(round(base + extra_activity + extra_heat))


def calc_calorie_goal(weight_kg: float, height_cm: float, age: int, activity_min: int = 0) -> int:
    # formula from assignment: базовый метаболизм
    bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    
    # Уровень активности добавляет калории (200-400 в зависимости от времени активности)
    # Формула: чем больше минут активности, тем больше добавка
    # 0-30 мин: +200 ккал, 30-60 мин: +300 ккал, >60 мин: +400 ккал
    if activity_min <= 30:
        activity_bonus = 200
    elif activity_min <= 60:
        activity_bonus = 300
    else:
        activity_bonus = 400
    
    return int(round(bmr + activity_bonus))


def workout_burned_calories(workout_type: str, minutes: int, weight_kg: float) -> int:
    # Minimal "smart" estimate (MET-based, coarse).
    # You can expand types if you want.
    t = (workout_type or "").lower().strip()

    met = 6.0  # default moderate
    if any(k in t for k in ["ходьба", "walk"]):
        met = 3.5
    elif any(k in t for k in ["бег", "run"]):
        met = 9.8
    elif any(k in t for k in ["вел", "bike", "cycling"]):
        met = 7.5
    elif any(k in t for k in ["сил", "gym", "weights"]):
        met = 6.0
    elif any(k in t for k in ["йог", "yoga", "растяж"]):
        met = 2.5

    # kcal = MET * 3.5 * weight(kg) / 200 * minutes
    kcal = met * 3.5 * weight_kg / 200.0 * minutes
    return int(round(kcal))


def workout_extra_water_ml(minutes: int) -> int:
    # assignment: +200 ml for each FULL 30 minutes workout (discrete calculation)
    # Например: 45 минут = 1 полный блок 30 минут = +200 мл
    full_30min_blocks = minutes // 30
    return full_30min_blocks * 200


def estimate_minutes_to_burn(calories: float, workout_type: str, weight_kg: float) -> int:
    """Сколько минут нужно, чтобы сжечь calories для заданного типа.

    Использует ту же MET-логику, что и workout_burned_calories.
    """
    calories = float(calories)
    if calories <= 0:
        return 0

    # kcal per minute
    t = (workout_type or "").lower().strip()
    met = 6.0
    if any(k in t for k in ["ходьба", "walk"]):
        met = 3.5
    elif any(k in t for k in ["бег", "run"]):
        met = 9.8
    elif any(k in t for k in ["вел", "bike", "cycling"]):
        met = 7.5
    elif any(k in t for k in ["сил", "gym", "weights"]):
        met = 6.0
    elif any(k in t for k in ["йог", "yoga", "растяж"]):
        met = 2.5

    kcal_per_min = met * 3.5 * float(weight_kg) / 200.0
    if kcal_per_min <= 0:
        return 0
    return int(round(calories / kcal_per_min))


def burn_recommendations(extra_kcal: float, weight_kg: float) -> str:
    """Короткие рекомендации по тренировкам, чтобы "сжечь" профицит."""
    extra_kcal = float(extra_kcal)
    if extra_kcal <= 0:
        return ""

    items = [
        ("быстрая ходьба", estimate_minutes_to_burn(extra_kcal, "ходьба", weight_kg)),
        ("велотренажёр", estimate_minutes_to_burn(extra_kcal, "вело", weight_kg)),
        ("бег", estimate_minutes_to_burn(extra_kcal, "бег", weight_kg)),
    ]
    items = [(n, m) for n, m in items if m > 0]
    if not items:
        return ""
    lines = "\n".join([f"- {n}: ~{m} мин" for n, m in items])
    return "\n\n💡 Чтобы компенсировать ~{:.0f} ккал, можно: \n{}".format(extra_kcal, lines)


def low_calorie_food_suggestions(remaining_kcal: float) -> str:
    """Простые идеи низкокалорийных продуктов в рамках остатка.

    Это не медицинская рекомендация, а практичные подсказки для бота.
    """
    remaining_kcal = float(remaining_kcal)
    if remaining_kcal <= 0:
        return ""

    items = [
        ("огурцы/помидоры", 20),
        ("яблоко", 52),
        ("греческий йогурт 2%", 80),
        ("творог 2%", 103),
        ("куриная грудка", 165),
    ]

    lines = []
    for name, kcal_100 in items:
        grams = int(round(min(300, max(50, remaining_kcal / kcal_100 * 100))))
        kcal = kcal_100 * grams / 100
        if kcal <= remaining_kcal * 1.1:
            lines.append(f"- {name}: ~{grams} г (~{kcal:.0f} ккал)")

    if not lines:
        return ""

    return "\n\n🥗 Идеи на остаток калорий: \n" + "\n".join(lines[:4])
