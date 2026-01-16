from aiogram.fsm.state import State, StatesGroup


class Profile(StatesGroup):
    weight = State()
    height = State()
    age = State()
    activity = State()
    city = State()
    calorie_goal = State()


class FoodLog(StatesGroup):
    waiting_choice = State()       # пользователь выбирает один из вариантов
    waiting_manual_kcal = State()  # пользователь вводит ккал/100г вручную
    waiting_serving_g = State()    # граммы в 1 шт/порции
    waiting_grams = State()        # сколько грамм съел (если не указано заранее)
    waiting_custom_kcal = State()  # для обратной совместимости
    waiting_fuzzy_confirm = State()  # для обратной совместимости


class WorkoutLog(StatesGroup):
    waiting_type = State()
    waiting_minutes = State()
