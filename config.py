import os

from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Токен Telegram бота (обязательно)
TOKEN = os.getenv("BOT_TOKEN")

# Где хранить данные пользователей (json-файл)
DATA_PATH = os.getenv("DATA_PATH", "data.json")

# Погода (необязательно):
# если ключ не задан, используем бесплатный Open-Meteo (без ключа)
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


if not TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")
