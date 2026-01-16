import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import TOKEN
from handlers import setup_handlers
from middlewares import LoggingMiddleware

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создаём экземпляры бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключаем middleware для логирования
dp.message.middleware(LoggingMiddleware())

# Подключаем все обработчики
setup_handlers(dp)


async def setup_bot_commands(bot: Bot):
    """Установка команд меню бота."""
    commands = [
        BotCommand(command="start", description="Приветствие и список команд"),
        BotCommand(command="help", description="Подробная справка"),
        BotCommand(command="set_profile", description="Настроить профиль (вес, рост, возраст, активность, город)"),
        BotCommand(command="log_water", description="Записать воду (например: /log_water 250)"),
        BotCommand(command="log_food", description="Записать еду (например: /log_food банан 1шт)"),
        BotCommand(command="add_food", description="Добавить продукт в личную базу"),
        BotCommand(command="log_workout", description="Записать тренировку (например: /log_workout бег 30)"),
        BotCommand(command="check_progress", description="Прогресс за сегодня"),
        BotCommand(command="plot", description="Графики прогресса (по умолчанию 14 дней)"),
        BotCommand(command="graphs", description="Графики прогресса (альтернативная команда)"),
        BotCommand(command="reset_today", description="Обнулить сегодняшние логи"),
    ]
    await bot.set_my_commands(commands)
    logger.info("Команды меню установлены!")


async def main():
    logger.info("Бот запущен!")
    try:
        # Устанавливаем команды меню
        await setup_bot_commands(bot)
        
        # На всякий случай убираем вебхук и "старые" апдейты
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
