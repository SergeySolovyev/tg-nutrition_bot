import asyncio
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def today_key() -> str:
    return date.today().isoformat()


def _default_day() -> Dict[str, Any]:
    # Агрегаты по дню + цели (для графиков)
    return {
        "logged_water_ml": 0,
        "logged_calories": 0.0,
        "burned_calories": 0.0,
        "workout_extra_water_ml": 0,
        # targets can be set per day so historical plots remain stable
        "water_target_ml": 0,
        "calorie_target": 0,
    }


@dataclass
class DataStore:
    path: Path
    _lock: asyncio.Lock

    @classmethod
    def create(cls, path: str) -> "DataStore":
        return cls(path=Path(path), _lock=asyncio.Lock())

    async def _load_nolock(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"users": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            # if file is corrupted, keep a backup and start fresh
            bak = self.path.with_suffix(".corrupted.json")
            self.path.replace(bak)
            return {"users": {}}

    async def _save_nolock(self, data: Dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_user(self, data: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        users = data.setdefault("users", {})
        u = users.setdefault(str(user_id), {})
        u.setdefault("profile", {})
        u.setdefault("days", {})
        u.setdefault("custom_foods", {})
        u.setdefault("history", {})  # для обратной совместимости
        return u

    def _ensure_day(self, u: Dict[str, Any], day: str) -> Dict[str, Any]:
        days = u.setdefault("days", {})
        d = days.setdefault(day, _default_day())
        # backward compatibility if old records exist
        for k, v in _default_day().items():
            d.setdefault(k, v)
        return d

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            await self._save_nolock(data)
            return u

    async def set_profile(self, user_id: int, profile: Dict[str, Any]) -> None:
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            u["profile"] = profile
            await self._save_nolock(data)

    async def get_day(self, user_id: int, day: Optional[str] = None) -> Dict[str, Any]:
        day = day or today_key()
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            d = self._ensure_day(u, day)
            await self._save_nolock(data)
            return d

    async def get_days(self, user_id: int) -> Dict[str, Any]:
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            days = u.setdefault("days", {})
            await self._save_nolock(data)
            return days

    async def get_last_days(self, user_id: int, limit: int = 14) -> List[Tuple[str, Dict[str, Any]]]:
        """Return list of (day_key, day_data) sorted ascending."""
        days = await self.get_days(user_id)
        keys = sorted(days.keys())
        if limit and limit > 0:
            keys = keys[-limit:]
        out: List[Tuple[str, Dict[str, Any]]] = []
        for k in keys:
            d = days.get(k) or {}
            # ensure defaults
            for dk, dv in _default_day().items():
                d.setdefault(dk, dv)
            out.append((k, d))
        return out

    async def set_day_targets(self, user_id: int, water_target_ml: int, calorie_target: int, day: Optional[str] = None) -> None:
        day = day or today_key()
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            d = self._ensure_day(u, day)
            d["water_target_ml"] = int(water_target_ml)
            d["calorie_target"] = int(calorie_target)
            await self._save_nolock(data)

    async def add_water(self, user_id: int, ml: int, day: Optional[str] = None) -> None:
        day = day or today_key()
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            d = self._ensure_day(u, day)
            d["logged_water_ml"] = int(d.get("logged_water_ml", 0)) + int(ml)
            await self._save_nolock(data)

    async def add_food(self, user_id: int, calories: float, day: Optional[str] = None) -> None:
        day = day or today_key()
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            d = self._ensure_day(u, day)
            d["logged_calories"] = float(d.get("logged_calories", 0)) + float(calories)
            await self._save_nolock(data)

    async def add_workout(self, user_id: int, burned: float, extra_water_ml: int, day: Optional[str] = None) -> None:
        day = day or today_key()
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            d = self._ensure_day(u, day)
            d["burned_calories"] = float(d.get("burned_calories", 0)) + float(burned)
            d["workout_extra_water_ml"] = int(d.get("workout_extra_water_ml", 0)) + int(extra_water_ml)
            await self._save_nolock(data)

    async def reset_today(self, user_id: int) -> None:
        """Reset aggregates for today, but keep the day's targets."""
        k = today_key()
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            old = self._ensure_day(u, k)
            water_target = int(old.get("water_target_ml", 0))
            cal_target = int(old.get("calorie_target", 0))
            u.setdefault("days", {})[k] = _default_day()
            u["days"][k]["water_target_ml"] = water_target
            u["days"][k]["calorie_target"] = cal_target
            await self._save_nolock(data)

    # ---------------------
    # Custom foods
    # ---------------------

    async def get_custom_foods(self, user_id: int) -> Dict[str, Any]:
        u = await self.get_user(user_id)
        return u.get("custom_foods") or {}

    async def upsert_custom_food(self, user_id: int, key: str, record: Dict[str, Any]) -> None:
        """key should be normalized name."""
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            cf = u.setdefault("custom_foods", {})
            cf[str(key)] = record
            await self._save_nolock(data)

    async def add_custom_food(self, user_id: int, food_name: str, kcal_100g: float) -> None:
        """Добавить кастомный продукт в словарь пользователя (для обратной совместимости)."""
        from utils import normalize_food_name
        key = normalize_food_name(food_name)
        record = {
            "name": food_name,
            "kcal_100g": float(kcal_100g),
            "serving_g": None,
            "source": "manual",
        }
        await self.upsert_custom_food(user_id, key, record)

    async def add_custom_alias(self, user_id: int, alias_key: str, target_key: str) -> None:
        """Map alias_key -> target_key by copying the record (simple approach)."""
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            cf = u.setdefault("custom_foods", {})
            if target_key in cf:
                cf[alias_key] = cf[target_key]
            await self._save_nolock(data)

    # ---------------------
    # History (для обратной совместимости и графиков)
    # ---------------------

    async def get_history(self, user_id: int) -> Dict[str, Dict[str, Any]]:
        """Получить историю пользователя (по датам) - для обратной совместимости."""
        days = await self.get_days(user_id)
        history = {}
        for day_key, day_data in days.items():
            history[day_key] = {
                "water_ml": int(day_data.get("logged_water_ml", 0)),
                "food_kcal": float(day_data.get("logged_calories", 0)),
                "workout_kcal": float(day_data.get("burned_calories", 0)),
                "water_target_ml": int(day_data.get("water_target_ml", 0)),
                "kcal_target": int(day_data.get("calorie_target", 0)),
            }
        return history

    async def update_history_targets(self, user_id: int, day: Optional[str] = None, temp: Optional[float] = None) -> None:
        """Обновить цели в истории для конкретного дня (вызывается из handlers).
        
        temp: температура для расчета цели воды (опционально, будет запрошена если не указана)
        """
        day = day or today_key()
        async with self._lock:
            data = await self._load_nolock()
            u = self._ensure_user(data, user_id)
            prof = u.get("profile", {})
            if not prof:
                return
            
            d = self._ensure_day(u, day)
            # Цели уже хранятся в days[day], так что просто сохраняем
            await self._save_nolock(data)
