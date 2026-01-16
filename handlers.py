from __future__ import annotations

import io
import logging
from typing import Any, Dict, Optional, Tuple

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from calc import (
    burn_recommendations,
    calc_calorie_goal,
    calc_water_goal_ml,
    low_calorie_food_suggestions,
    workout_burned_calories,
    workout_extra_water_ml,
)
from config import DATA_PATH
from states import FoodLog, Profile, WorkoutLog
from storage import DataStore
from utils import (
    estimate_food_option,
    normalize_food_name,
    split_food_and_amount,
)
from utils import get_city_temperature_c

logger = logging.getLogger(__name__)


router = Router()
store = DataStore.create(DATA_PATH)


def parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def parse_float(s: str) -> Optional[float]:
    try:
        return float(str(s).strip().replace(",", "."))
    except Exception:
        return None


async def ensure_profile(user_id: int) -> Optional[dict]:
    u = await store.get_user(user_id)
    prof = u.get("profile") or {}
    required = ["weight_kg", "height_cm", "age", "activity_min", "city", "calorie_goal"]
    if all(k in prof and prof[k] is not None for k in required):
        return prof
    return None


def _progress_text(
    water_goal_base: int,
    workout_extra_water: int,
    cal_goal: int,
    logged_water: int,
    logged_cal: float,
    burned: float,
) -> str:
    water_goal_total = int(water_goal_base) + int(workout_extra_water)
    remaining_water = max(0, water_goal_total - logged_water)

    net_consumed = logged_cal - burned
    remaining_cal = cal_goal - net_consumed

    extra_line = (
        f"- Доп. цель из-за тренировок: {int(workout_extra_water)} мл.\n" if workout_extra_water else ""
    )

    return (
        "📊 Прогресс:\n"
        "Вода:\n"
        f"- Выпито: {logged_water} мл из {water_goal_total} мл.\n"
        f"{extra_line}"
        f"- Осталось: {remaining_water} мл.\n\n"
        "Калории:\n"
        f"- Потреблено: {logged_cal:.0f} ккал из {cal_goal} ккал.\n"
        f"- Сожжено: {burned:.0f} ккал.\n"
        f"- Баланс (нетто): {net_consumed:.0f} ккал.\n"
        f"- Остаток до цели: {remaining_cal:.0f} ккал."
    )


def _food_choice_keyboard(options: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for idx, opt in enumerate(options[:3]):
        name = opt.get("name", "?")
        kcal = opt.get("kcal_100g", 0)
        buttons.append(
            [InlineKeyboardButton(text=f"{name} ({kcal:.0f} ккал/100г)", callback_data=f"foodpick:{idx}")]
        )
    buttons.append([InlineKeyboardButton(text="Ввести вручную", callback_data="foodmanual")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _ensure_targets_for_today(user_id: int, prof: dict) -> Tuple[int, int]:
    """Записываем цели дня (для графиков)."""
    temp = await get_city_temperature_c(prof["city"])
    water_goal_base = calc_water_goal_ml(prof["weight_kg"], prof["activity_min"], temp)
    cal_goal = int(prof["calorie_goal"])
    await store.set_day_targets(user_id, water_goal_base, cal_goal)
    return water_goal_base, cal_goal


# -----------------------
# /start, /help
# -----------------------


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я бот для расчёта нормы воды/калорий и трекинга.\n\n"
        "Команды:\n"
        "/set_profile — заполнить профиль\n"
        "/log_water <мл> — записать воду\n"
        "/log_food <продукт> [кол-во] — записать еду (пример: /log_food банан 1шт или /log_food рис 150)\n"
        "/log_workout <тип> <мин> — записать тренировку\n"
        "/check_progress — посмотреть прогресс за сегодня\n"
        "/plot [дни] — графики прогресса (по умолчанию 14 дней)\n"
        "/add_food <название> <ккал/100г> [грамм_в_1шт] — добавить продукт в личную базу\n"
        "/reset_today — обнулить сегодняшние логи\n"
        "/help — помощь"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Как это работает:\n"
        "1) /set_profile — задаёшь вес, рост, возраст, активность, город и цель калорий.\n"
        "2) Норма воды = вес*30мл + 500мл за каждые 30 мин активности + добавка за жару (>25°C).\n"
        "3) /log_water — прибавляет выпитую воду.\n"
        "4) /log_food — умно определяет калорийность: OpenFoodFacts + восстановление из БЖУ + робастный выбор + личная база.\n"
        "5) /log_workout — оценивает сожжённые калории и добавляет воду (+200мл за каждые 30мин).\n"
        "6) /plot — отправляет графики по воде и калориям.\n\n"
        "Подсказки:\n"
        "- Еду можно вводить с количеством: '150', '250мл', '2шт', '1 порция'.\n"
        "- Если продукт не найден — бот попросит ввести ккал/100г и запомнит.\n"
        "- /add_food позволяет заранее добавить продукт в личную базу."
    )


# -----------------------
# Profile FSM: /set_profile
# -----------------------


@router.message(Command("set_profile"))
async def set_profile(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Profile.weight)
    await message.answer("Введите ваш вес (кг):")


@router.message(Profile.weight)
async def profile_weight(message: Message, state: FSMContext):
    w = parse_float(message.text)
    if w is None or w <= 0 or w > 400:
        await message.answer("Вес должен быть числом (кг). Например: 80")
        return
    await state.update_data(weight_kg=w)
    await state.set_state(Profile.height)
    await message.answer("Введите ваш рост (см):")


@router.message(Profile.height)
async def profile_height(message: Message, state: FSMContext):
    h = parse_float(message.text)
    if h is None or h <= 0 or h > 260:
        await message.answer("Рост должен быть числом (см). Например: 180")
        return
    await state.update_data(height_cm=h)
    await state.set_state(Profile.age)
    await message.answer("Введите ваш возраст (лет):")


@router.message(Profile.age)
async def profile_age(message: Message, state: FSMContext):
    a = parse_int(message.text)
    if a is None or a <= 0 or a > 120:
        await message.answer("Возраст должен быть целым числом. Например: 35")
        return
    await state.update_data(age=a)
    await state.set_state(Profile.activity)
    await message.answer("Сколько минут активности в день (в среднем)? Например: 45")


@router.message(Profile.activity)
async def profile_activity(message: Message, state: FSMContext):
    m = parse_int(message.text)
    if m is None or m < 0 or m > 1440:
        await message.answer("Минуты активности должны быть целым числом. Например: 45")
        return
    await state.update_data(activity_min=m)
    await state.set_state(Profile.city)
    await message.answer("В каком городе вы находитесь? (например: Moscow)")


@router.message(Profile.city)
async def profile_city(message: Message, state: FSMContext):
    city = (message.text or "").strip()
    if len(city) < 2:
        await message.answer("Напишите город текстом. Например: Moscow")
        return
    await state.update_data(city=city)
    await state.set_state(Profile.calorie_goal)

    data = await state.get_data()
    suggested = calc_calorie_goal(data["weight_kg"], data["height_cm"], data["age"], data["activity_min"])
    await message.answer(
        "Цель калорий на день.\n"
        f"Я могу рассчитать по формуле: {suggested} ккал.\n"
        "Введите число, или отправьте 0 чтобы принять расчёт:"
    )


@router.message(Profile.calorie_goal)
async def profile_cal_goal(message: Message, state: FSMContext):
    val = parse_int(message.text)
    if val is None:
        await message.answer("Введите целое число, например 2500, или 0 чтобы принять расчёт.")
        return

    data = await state.get_data()
    suggested = calc_calorie_goal(data["weight_kg"], data["height_cm"], data["age"], data["activity_min"])
    cal_goal = suggested if val == 0 else val
    if cal_goal <= 0 or cal_goal > 10000:
        await message.answer("Цель калорий должна быть в разумных пределах. Например 2500 (или 0).")
        return

    profile = {
        "weight_kg": float(data["weight_kg"]),
        "height_cm": float(data["height_cm"]),
        "age": int(data["age"]),
        "activity_min": int(data["activity_min"]),
        "city": str(data["city"]),
        "calorie_goal": int(cal_goal),
    }
    await store.set_profile(message.from_user.id, profile)
    await state.clear()

    temp = await get_city_temperature_c(profile["city"])
    water_goal = calc_water_goal_ml(profile["weight_kg"], profile["activity_min"], temp)
    await store.set_day_targets(message.from_user.id, water_goal, profile["calorie_goal"])

    temp_line = f" (сейчас ~{temp:.1f}°C)" if temp is not None else ""

    await message.answer(
        "✅ Профиль сохранён!\n"
        f"Город: {profile['city']}{temp_line}\n"
        f"Норма воды: {water_goal} мл/день\n"
        f"Цель калорий: {profile['calorie_goal']} ккал/день\n\n"
        "🎉 Всё установлено! Профиль готов к использованию.\n"
        "Теперь можно: /log_water, /log_food, /log_workout, /check_progress"
    )


# -----------------------
# /add_food (custom db)
# -----------------------


@router.message(Command("add_food"))
async def cmd_add_food(message: Message, command: CommandObject):
    prof = await ensure_profile(message.from_user.id)
    if not prof:
        await message.answer("Сначала настрой профиль: /set_profile")
        return

    args = (command.args or "").strip()
    if not args:
        await message.answer("Использование: /add_food <название> <ккал/100г> [грамм_в_1шт]\nПример: /add_food банан 89 120")
        return

    parts = args.split()
    if len(parts) < 2:
        await message.answer("Нужно минимум: <название> <ккал/100г>.")
        return

    # last token is kcal, optional serving_g after it? (we allow both orders)
    # Format we support: name... kcal [serving_g]
    kcal = parse_float(parts[-1])
    serving_g = None

    name_parts = parts[:-1]
    if kcal is None and len(parts) >= 3:
        # maybe name kcal serving
        kcal = parse_float(parts[-2])
        serving_g = parse_float(parts[-1])
        name_parts = parts[:-2]

    if kcal is None:
        await message.answer("Не понял ккал/100г. Пример: /add_food банан 89")
        return

    if len(parts) >= 3 and serving_g is None:
        # maybe provided serving_g as third token from end
        maybe_serv = parse_float(parts[-1])
        maybe_kcal = parse_float(parts[-2])
        if maybe_kcal is not None and maybe_serv is not None:
            kcal = maybe_kcal
            serving_g = maybe_serv
            name_parts = parts[:-2]

    name = " ".join(name_parts).strip()
    if not name:
        await message.answer("Не понял название продукта.")
        return

    key = normalize_food_name(name)
    record = {
        "name": name,
        "kcal_100g": float(kcal),
        "serving_g": float(serving_g) if serving_g is not None else None,
        "source": "manual",
    }
    await store.upsert_custom_food(message.from_user.id, key, record)

    s_line = f"; 1 шт/порция = {serving_g:.0f} г" if serving_g is not None else ""
    await message.answer(f"✅ Запомнил: {name} = {kcal:.0f} ккал/100г{s_line}.")


# -----------------------
# /log_water
# -----------------------


@router.message(Command("log_water"))
async def cmd_log_water(message: Message, command: CommandObject):
    prof = await ensure_profile(message.from_user.id)
    if not prof:
        await message.answer("Сначала настрой профиль: /set_profile")
        return

    arg = (command.args or "").strip()
    ml = parse_int(arg)
    if ml is None or ml <= 0 or ml > 5000:
        await message.answer("Использование: /log_water <мл> (например /log_water 250)")
        return

    water_goal_base, cal_goal = await _ensure_targets_for_today(message.from_user.id, prof)

    await store.add_water(message.from_user.id, ml)
    day = await store.get_day(message.from_user.id)

    await message.answer(
        f"✅ Записал {ml} мл воды.\n"
        + _progress_text(
            water_goal_base,
            int(day.get("workout_extra_water_ml", 0)),
            cal_goal,
            int(day.get("logged_water_ml", 0)),
            float(day.get("logged_calories", 0)),
            float(day.get("burned_calories", 0)),
        )
    )


# -----------------------
# /log_food (FSM + advanced calories)
# -----------------------


@router.message(Command("log_food"))
async def cmd_log_food(message: Message, state: FSMContext, command: CommandObject):
    prof = await ensure_profile(message.from_user.id)
    if not prof:
        await message.answer("Сначала настрой профиль: /set_profile")
        return

    raw = (command.args or "").strip()
    if not raw:
        await message.answer("Использование: /log_food <название продукта> [кол-во] (например /log_food банан 1шт)")
        return

    await _ensure_targets_for_today(message.from_user.id, prof)

    food_q, qty, unit = split_food_and_amount(raw)
    if not food_q:
        await message.answer("Не понял название продукта.")
        return

    custom_foods = await store.get_custom_foods(message.from_user.id)
    res = await estimate_food_option(food_q, custom_foods=custom_foods, limit=10)

    await state.clear()
    await state.update_data(food_query=food_q, qty=qty, unit=unit)

    if res.get("status") == "manual":
        await state.set_state(FoodLog.waiting_manual_kcal)
        await message.answer(
            "Не смог уверенно определить калорийность.\n"
            f"Введите ккал на 100 г для: '{food_q}' (например 89).\n"
            "Я запомню это в личной базе."
        )
        return

    if res.get("status") == "choose":
        options = [o.__dict__ if hasattr(o, "__dict__") else o for o in (res.get("options") or [])]
        await state.update_data(food_options=options)
        await state.set_state(FoodLog.waiting_choice)
        conf = int(res.get("confidence", 0))
        await message.answer(
            f"Нашёл несколько вариантов для '{food_q}' (уверенность {conf}%). Выбери правильный:",
            reply_markup=_food_choice_keyboard(options),
        )
        return

    chosen = res.get("chosen")
    if not chosen:
        await state.set_state(FoodLog.waiting_manual_kcal)
        await message.answer(
            "Не смог определить калорийность.\n"
            f"Введите ккал на 100 г для: '{food_q}' (например 89)."
        )
        return

    # chosen may be FoodOption dataclass
    if hasattr(chosen, "__dict__"):
        chosen = chosen.__dict__

    await _start_food_flow(message, state, prof, chosen)


@router.callback_query(lambda c: c.data and c.data.startswith("foodpick:"))
async def cb_food_pick(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    prof = await ensure_profile(callback.from_user.id)
    if not prof:
        await callback.message.answer("Сначала настрой профиль: /set_profile")
        return

    data = await state.get_data()
    options = data.get("food_options") or []

    try:
        idx = int(callback.data.split(":", 1)[1])
    except Exception:
        await callback.message.answer("Не понял выбор. Попробуйте снова: /log_food")
        await state.clear()
        return

    if idx < 0 or idx >= len(options):
        await callback.message.answer("Не нашёл этот вариант. Попробуйте снова: /log_food")
        await state.clear()
        return

    chosen = options[idx]
    await _start_food_flow(callback.message, state, prof, chosen)


@router.callback_query(lambda c: c.data == "foodmanual")
async def cb_food_manual(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    food_q = data.get("food_query")
    await state.set_state(FoodLog.waiting_manual_kcal)
    await callback.message.answer(
        f"Ок. Введите ккал на 100 г для: '{food_q}' (например 89).\nЯ запомню это в личной базе."
    )


async def _start_food_flow(message: Message, state: FSMContext, prof: dict, chosen: Dict[str, Any]):
    """После того как мы получили калорийность (и, возможно, serving_g), решаем вопрос количества."""
    food_q = (await state.get_data()).get("food_query") or chosen.get("name")
    qty = (await state.get_data()).get("qty")
    unit = (await state.get_data()).get("unit")

    name = str(chosen.get("name") or food_q)
    kcal_100 = float(chosen.get("kcal_100g") or 0.0)
    serving_g = chosen.get("serving_g")

    await state.update_data(food_name=name, kcal_100=kcal_100, serving_g=serving_g, source=chosen.get("source"), confidence=chosen.get("score"))

    # If user already provided quantity
    if qty is not None and unit is not None:
        grams = await _resolve_grams(message, state, name, qty, unit, serving_g)
        if grams is None:
            return  # state set to waiting_serving_g
        await _finish_food_log(message, state, prof, name, kcal_100, grams)
        return

    await state.set_state(FoodLog.waiting_grams)
    await message.answer(f"🍽️ {name} — примерно {kcal_100:.0f} ккал на 100 г. Сколько грамм вы съели?")


async def _resolve_grams(
    message: Message,
    state: FSMContext,
    food_name: str,
    qty: float,
    unit: str,
    serving_g: Optional[float],
) -> Optional[float]:
    """Convert user quantity into grams. If we need serving size -> switch to waiting_serving_g."""
    qty = float(qty)

    if unit in ("g", "ml"):
        # ml treated like grams (density=1)
        return qty

    if unit in ("piece", "serving", "auto"):
        if serving_g is None:
            # ask user once; we'll remember if they choose to
            await state.set_state(FoodLog.waiting_serving_g)
            await state.update_data(qty=qty, unit=unit)
            await message.answer(
                f"Вы указали количество ({qty:g}). Сколько грамм в 1 шт/порции для '{food_name}'?\n"
                "Например: 120"
            )
            return None
        return qty * float(serving_g)

    return None


@router.message(FoodLog.waiting_serving_g)
async def food_serving_g(message: Message, state: FSMContext):
    g = parse_float(message.text)
    if g is None or g <= 0 or g > 2000:
        await message.answer("Введите граммы для 1 шт/порции числом. Например: 120")
        return

    data = await state.get_data()
    qty = float(data.get("qty") or 1.0)
    unit = data.get("unit") or "piece"
    name = str(data.get("food_name") or data.get("food_query") or "продукт")
    grams = qty * float(g)

    # persist serving_g in custom_foods for this name (normalized)
    key = normalize_food_name(name)
    custom_foods = await store.get_custom_foods(message.from_user.id)
    existing = custom_foods.get(key) or {"name": name, "kcal_100g": float(data.get("kcal_100") or 0.0), "source": "manual"}
    existing["serving_g"] = float(g)
    await store.upsert_custom_food(message.from_user.id, key, existing)

    prof = await ensure_profile(message.from_user.id)
    await _finish_food_log(message, state, prof, name, float(data.get("kcal_100") or 0.0), grams)


@router.message(FoodLog.waiting_manual_kcal)
async def food_manual_kcal(message: Message, state: FSMContext):
    kcal = parse_float(message.text)
    if kcal is None or kcal <= 0 or kcal > 2000:
        await message.answer("Введите ккал/100г числом (например 89).")
        return

    data = await state.get_data()
    food_q = str(data.get("food_query") or "продукт")
    name = food_q

    # save to custom db
    key = normalize_food_name(food_q)
    record = {"name": name, "kcal_100g": float(kcal), "serving_g": None, "source": "manual"}
    await store.upsert_custom_food(message.from_user.id, key, record)

    # now ask grams (or continue if qty was provided)
    qty = data.get("qty")
    unit = data.get("unit")
    await state.update_data(food_name=name, kcal_100=float(kcal), serving_g=None, source="manual", confidence=100)

    prof = await ensure_profile(message.from_user.id)
    if qty is not None and unit is not None:
        grams = await _resolve_grams(message, state, name, float(qty), str(unit), None)
        if grams is None:
            return
        await _finish_food_log(message, state, prof, name, float(kcal), grams)
        return

    await state.set_state(FoodLog.waiting_grams)
    await message.answer(f"Ок. '{name}' = {kcal:.0f} ккал/100г. Сколько грамм вы съели?")


@router.message(FoodLog.waiting_choice)
async def food_choice_text_fallback(message: Message, state: FSMContext):
    # user typed instead of clicking
    await message.answer("Пожалуйста, выбери вариант кнопкой ниже или введи /log_food заново.")


@router.message(FoodLog.waiting_grams)
async def food_grams(message: Message, state: FSMContext):
    grams = parse_float(message.text)
    if grams is None or grams <= 0 or grams > 5000:
        await message.answer("Введите граммы числом (например 150).")
        return

    data = await state.get_data()
    kcal_100 = float(data["kcal_100"])
    name = str(data["food_name"])

    prof = await ensure_profile(message.from_user.id)
    await _finish_food_log(message, state, prof, name, kcal_100, grams)


async def _finish_food_log(message: Message, state: FSMContext, prof: dict, name: str, kcal_100: float, grams: float):
    calories = float(kcal_100) * (float(grams) / 100.0)
    await store.add_food(message.from_user.id, calories)
    await state.clear()

    water_goal_base, cal_goal = await _ensure_targets_for_today(message.from_user.id, prof)
    day = await store.get_day(message.from_user.id)

    await message.answer(
        f"✅ Записано: {calories:.0f} ккал ({name}, {grams:.0f} г).\n"
        + _progress_text(
            water_goal_base,
            int(day.get("workout_extra_water_ml", 0)),
            cal_goal,
            int(day.get("logged_water_ml", 0)),
            float(day.get("logged_calories", 0)),
            float(day.get("burned_calories", 0)),
        )
    )


# -----------------------
# /log_workout (FSM)
# -----------------------


@router.message(Command("log_workout"))
async def cmd_log_workout(message: Message, state: FSMContext, command: CommandObject):
    prof = await ensure_profile(message.from_user.id)
    if not prof:
        await message.answer("Сначала настрой профиль: /set_profile")
        return

    await _ensure_targets_for_today(message.from_user.id, prof)

    args = (command.args or "").strip()
    if not args:
        await state.clear()
        await state.set_state(WorkoutLog.waiting_type)
        await message.answer("Введите тип тренировки (например: бег / ходьба / вело / силовая):")
        return

    parts = args.split()
    if len(parts) < 2:
        await message.answer("Использование: /log_workout <тип> <мин> (например /log_workout бег 30)")
        return

    workout_type = " ".join(parts[:-1])
    minutes = parse_int(parts[-1])
    if minutes is None or minutes <= 0 or minutes > 1000:
        await message.answer("Минуты должны быть целым числом. Например: /log_workout бег 30")
        return

    burned = workout_burned_calories(workout_type, minutes, prof["weight_kg"])
    extra_water = workout_extra_water_ml(minutes)
    await store.add_workout(message.from_user.id, burned, extra_water)

    day = await store.get_day(message.from_user.id)
    water_goal_base, cal_goal = await _ensure_targets_for_today(message.from_user.id, prof)

    await message.answer(
        f"🏃‍♂️ Тренировка записана: {workout_type}, {minutes} мин.\n"
        f"Сожжено: ~{burned} ккал.\n"
        f"Доп. вода из-за тренировки: +{extra_water} мл к дневной норме.\n\n"
        + _progress_text(
            water_goal_base,
            int(day.get("workout_extra_water_ml", 0)),
            cal_goal,
            int(day.get("logged_water_ml", 0)),
            float(day.get("logged_calories", 0)),
            float(day.get("burned_calories", 0)),
        )
    )


@router.message(WorkoutLog.waiting_type)
async def workout_type_step(message: Message, state: FSMContext):
    t = (message.text or "").strip()
    if len(t) < 2:
        await message.answer("Введите тип тренировки текстом. Например: бег")
        return
    await state.update_data(workout_type=t)
    await state.set_state(WorkoutLog.waiting_minutes)
    await message.answer("Сколько минут? (например 30)")


@router.message(WorkoutLog.waiting_minutes)
async def workout_minutes_step(message: Message, state: FSMContext):
    minutes = parse_int(message.text)
    if minutes is None or minutes <= 0 or minutes > 1000:
        await message.answer("Минуты должны быть целым числом. Например: 30")
        return

    data = await state.get_data()
    workout_type = str(data["workout_type"])

    prof = await ensure_profile(message.from_user.id)
    burned = workout_burned_calories(workout_type, minutes, prof["weight_kg"])
    extra_water = workout_extra_water_ml(minutes)
    await store.add_workout(message.from_user.id, burned, extra_water)
    await state.clear()

    day = await store.get_day(message.from_user.id)
    water_goal_base, cal_goal = await _ensure_targets_for_today(message.from_user.id, prof)

    await message.answer(
        f"🏃‍♂️ Тренировка записана: {workout_type}, {minutes} мин.\n"
        f"Сожжено: ~{burned} ккал.\n"
        f"Доп. вода из-за тренировки: +{extra_water} мл к дневной норме.\n\n"
        + _progress_text(
            water_goal_base,
            int(day.get("workout_extra_water_ml", 0)),
            cal_goal,
            int(day.get("logged_water_ml", 0)),
            float(day.get("logged_calories", 0)),
            float(day.get("burned_calories", 0)),
        )
    )


# -----------------------
# /check_progress, /plot, /reset_today
# -----------------------


@router.message(Command("check_progress"))
async def cmd_check_progress(message: Message):
    try:
        prof = await ensure_profile(message.from_user.id)
        if not prof:
            await message.answer("Сначала настрой профиль: /set_profile")
            return

        water_goal_base, cal_goal = await _ensure_targets_for_today(message.from_user.id, prof)
        day = await store.get_day(message.from_user.id)

        temp = await get_city_temperature_c(prof["city"])
        temp_line = f" (сейчас ~{temp:.1f}°C)" if temp is not None else ""

        logged_cal = float(day.get("logged_calories", 0))
        burned = float(day.get("burned_calories", 0))
        net = logged_cal - burned
        remaining = cal_goal - net

        recs = ""
        if net > cal_goal:
            recs = burn_recommendations(net - cal_goal, prof["weight_kg"])
        elif remaining > 150:
            # если до цели ещё далеко — подскажем низкокалорийные варианты
            recs = low_calorie_food_suggestions(remaining)

        await message.answer(
            f"📍 Город: {prof['city']}{temp_line}\n"
            + _progress_text(
                water_goal_base,
                int(day.get("workout_extra_water_ml", 0)),
                cal_goal,
                int(day.get("logged_water_ml", 0)),
                logged_cal,
                burned,
            )
            + recs
        )
    except Exception as e:
        logger.error(f"Ошибка при получении прогресса для пользователя {message.from_user.id}: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при получении прогресса: {str(e)}")


@router.message(Command("plot"))
async def cmd_plot(message: Message, command: CommandObject):
    prof = await ensure_profile(message.from_user.id)
    if not prof:
        await message.answer("Сначала настрой профиль: /set_profile")
        return

    days_arg = (command.args or "").strip()
    limit = parse_int(days_arg) if days_arg else 14
    if limit is None or limit <= 0 or limit > 365:
        limit = 14

    # lazy import for faster bot start
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = await store.get_last_days(message.from_user.id, limit=limit)
    if not rows:
        await message.answer("Пока нет данных для графиков. Сделай хотя бы один /log_water или /log_food")
        return

    labels = []
    water = []
    water_goal = []
    cal = []
    cal_goal = []

    for day_key, d in rows:
        labels.append(day_key[5:])  # MM-DD
        water.append(int(d.get("logged_water_ml", 0)))
        wg = int(d.get("water_target_ml", 0)) + int(d.get("workout_extra_water_ml", 0))
        water_goal.append(wg)
        cal.append(float(d.get("logged_calories", 0)))
        cg = int(d.get("calorie_target", 0)) or int(prof.get("calorie_goal", 0))
        cal_goal.append(cg)

    # Water plot
    fig = plt.figure()
    plt.plot(labels, water, marker="o")
    plt.plot(labels, water_goal, marker="o")
    plt.title("Вода: выпито vs цель")
    plt.xlabel("Дата")
    plt.ylabel("мл")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    buf1 = io.BytesIO()
    fig.savefig(buf1, format="png")
    plt.close(fig)
    buf1.seek(0)

    # Calories plot
    fig2 = plt.figure()
    plt.plot(labels, cal, marker="o")
    plt.plot(labels, cal_goal, marker="o")
    plt.title("Калории: съедено vs цель")
    plt.xlabel("Дата")
    plt.ylabel("ккал")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    buf2 = io.BytesIO()
    fig2.savefig(buf2, format="png")
    plt.close(fig2)
    buf2.seek(0)

    await message.answer_photo(BufferedInputFile(buf1.getvalue(), filename="water.png"), caption="График воды")
    await message.answer_photo(BufferedInputFile(buf2.getvalue(), filename="calories.png"), caption="График калорий")


@router.message(Command("reset_today"))
async def cmd_reset_today(message: Message):
    await store.reset_today(message.from_user.id)
    await message.answer("✅ Сегодняшние логи обнулены. /check_progress")


# -----------------------
# Фоллбек на неизвестные команды
# -----------------------


@router.message()
async def fallback(message: Message):
    if message.text and message.text.startswith("/"):
        await message.answer("Неизвестная команда. /help")


def setup_handlers(dp):
    """Подключение всех обработчиков к Dispatcher."""
    dp.include_router(router)
