# 🚀 Быстрая инструкция по загрузке на GitHub

## Шаг 1: Настройте Git (если еще не настроено)

Выполните в терминале (замените на свои данные):

```bash
cd "c:\Yandex.Disk\Yandex.Disk\Phyton Practical HSE\tg bot\final_version"

git config user.email "your-email@example.com"
git config user.name "SergeySolovyev"
```

Или глобально для всех репозиториев:
```bash
git config --global user.email "your-email@example.com"
git config --global user.name "SergeySolovyev"
```

## Шаг 2: Создайте коммит

```bash
cd "c:\Yandex.Disk\Yandex.Disk\Phyton Practical HSE\tg bot\final_version"

git commit -m "Initial commit: Telegram nutrition bot with advanced features"
```

## Шаг 3: Загрузите на GitHub

```bash
git push -u origin main
```

**Если запросит авторизацию:**
- Используйте **Personal Access Token** (не пароль GitHub)
- Получить токен: GitHub.com → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token
- Выберите scope: `repo`
- Скопируйте токен и используйте его как пароль

## ✅ Проверка

После успешной загрузки проверьте:
- https://github.com/SergeySolovyev/tg-nutrition_bot
- Все файлы должны быть видны
- `.env` и `data.json` НЕ должны быть видны (они в .gitignore)

## 🌐 Дальше - деплой на Render.com

См. `DEPLOY_INSTRUCTIONS.md` для инструкций по деплою на Render.com
