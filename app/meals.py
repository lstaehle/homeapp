import json
from datetime import date
from pathlib import Path

_PLAN_FILE = Path("data/meals_plan.json")
_LIST_FILE = Path("data/meals_list.json")

_DEFAULT_MEALS = [
    "5P",
    "Risotto",
    "Spaghetti Bolognese",
    "Pizza",
    "Hähnchen mit Reis",
    "Gemüsesuppe",
    "Zürcher Geschnetzeltes",
    "Hackfleisch-Auflauf",
    "Fischstäbchen",
    "Pfannkuchen",
]


def _load_plan() -> dict:
    if not _PLAN_FILE.exists():
        return {}
    return json.loads(_PLAN_FILE.read_text())


def _save_plan(plan: dict) -> None:
    _PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PLAN_FILE.write_text(json.dumps(plan, ensure_ascii=False, indent=2))


def _load_list() -> list[str]:
    if not _LIST_FILE.exists():
        return list(_DEFAULT_MEALS)
    return json.loads(_LIST_FILE.read_text())


def _save_list(meals: list[str]) -> None:
    _LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LIST_FILE.write_text(json.dumps(meals, ensure_ascii=False, indent=2))


def get_plan() -> dict:
    return _load_plan()


def set_meal(day: date, meal: str) -> None:
    plan = _load_plan()
    plan[day.isoformat()] = meal
    _save_plan(plan)


def delete_meal(day: date) -> None:
    plan = _load_plan()
    plan.pop(day.isoformat(), None)
    _save_plan(plan)


def get_meal_list() -> list[str]:
    return _load_list()


def add_to_meal_list(meal: str) -> None:
    meals = _load_list()
    if meal not in meals:
        meals.append(meal)
        _save_list(meals)
