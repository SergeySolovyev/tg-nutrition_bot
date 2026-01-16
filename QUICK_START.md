# ⚡ Быстрый старт - загрузка на GitHub и деплой

## 📤 Загрузка на GitHub (3 команды)

Откройте терминал в папке `final_version` и выполните:

```bash
# 1. Настройте Git (замените email на свой)
git config user.email "your-email@example.com"
git config user.name "SergeySolovyev"

# 2. Создайте коммит
git commit -m "Initial commit: Telegram nutrition bot"

# 3. Загрузите на GitHub
git push -u origin main
```

**Если запросит пароль:** используйте Personal Access Token (см. ниже)

## 🔑 Получение Personal Access Token

1. Зайдите на https://github.com/settings/tokens
2. Нажмите "Generate new token (classic)"
3. Выберите scope: `repo` (полный доступ)
4. Скопируйте токен
5. Используйте токен как пароль при `git push`

## 🌐 Деплой на Render.com

После загрузки на GitHub:

1. Зайдите на https://render.com
2. New → Web Service
3. Подключите репозиторий `SergeySolovyev/tg-nutrition_bot`
4. Настройки:
   - **Start Command**: `python bot.py`
   - **Environment**: Python 3
5. Добавьте переменные:
   - `BOT_TOKEN` = ваш токен от @BotFather
6. Deploy!

Подробнее: см. `DEPLOY_INSTRUCTIONS.md`
