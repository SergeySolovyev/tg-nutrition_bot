import logging

from aiogram import BaseMiddleware
from aiogram.types import Message

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Middleware для логирования всех команд пользователя (для деплоя на Render)"""
    
    async def __call__(self, handler, event: Message, data: dict):
        if isinstance(event, Message) and event.text:
            user_id = event.from_user.id
            username = event.from_user.username or "без username"
            text = event.text.strip()
            # Логируем в формате для Render (stdout через logging)
            logger.info(f"User {user_id} (@{username}): {text}")
        return await handler(event, data)
