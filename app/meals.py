import json
from datetime import date, timedelta
from pathlib import Path

_PLAN_FILE = Path("data/meals_plan.json")
_LIST_FILE = Path("data/meals_list.json")

_DEFAULT_MEAL_NAMES = [
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

GERMAN_DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_plan() -> dict:
    if not _PLAN_FILE.exists():
        return {}
    return json.loads(_PLAN_FILE.read_text())


def _save_plan(plan: dict) -> None:
    _PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PLAN_FILE.write_text(json.dumps(plan, ensure_ascii=False, indent=2))


def _load_list() -> list[dict]:
    if not _LIST_FILE.exists():
        return [{"name": m, "ingredients": []} for m in _DEFAULT_MEAL_NAMES]
    data = json.loads(_LIST_FILE.read_text())
    # Migrate flat string meal list
    if data and isinstance(data[0], str):
        return [{"name": m, "ingredients": []} for m in data]
    # Migrate string ingredients → {"name": str, "section_id": None}
    for meal in data:
        meal["ingredients"] = [
            ing if isinstance(ing, dict) else {"name": ing, "section_id": None}
            for ing in meal.get("ingredients", [])
        ]
    return data


def _save_list(meals: list[dict]) -> None:
    _LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LIST_FILE.write_text(json.dumps(meals, ensure_ascii=False, indent=2))



# ---------------------------------------------------------------------------
# Meal plan
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Meal list & ingredients
# ---------------------------------------------------------------------------

def get_meal_list() -> list[dict]:
    """Returns meals sorted A-Z, each with ingredients sorted A-Z."""
    meals = _load_list()
    for meal in meals:
        meal["ingredients"] = sorted(meal["ingredients"], key=lambda i: i["name"].casefold())
    return sorted(meals, key=lambda m: m["name"].casefold())


def get_meal_names() -> list[str]:
    return [m["name"] for m in get_meal_list()]


def add_to_meal_list(meal: str) -> None:
    meals = _load_list()
    if not any(m["name"] == meal for m in meals):
        meals.append({"name": meal, "ingredients": []})
        _save_list(meals)


def delete_from_meal_list(meal_name: str) -> None:
    meals = _load_list()
    _save_list([m for m in meals if m["name"] != meal_name])


def set_meal_ingredients(meal_name: str, ingredients: list[str]) -> None:
    meals = _load_list()
    for m in meals:
        if m["name"] == meal_name:
            m["ingredients"] = ingredients
            _save_list(meals)
            return


# ---------------------------------------------------------------------------
# Pending grocery ingredients
# ---------------------------------------------------------------------------

def get_pending_ingredients() -> list[dict]:
    """
    Returns ingredients from planned meals for today + next 6 days.
    [{"label": "Fr 05.06.", "meal": str, "ingredients": [str]}]
    """
    plan = _load_plan()
    meals_map = {m["name"]: m["ingredients"] for m in _load_list()}
    today = date.today()

    result = []
    for i in range(7):
        day = today + timedelta(days=i)
        meal_name = plan.get(day.isoformat())
        if not meal_name:
            continue
        ingredients = meals_map.get(meal_name, [])
        if not ingredients:
            continue
        label = f"{'Heute' if i == 0 else GERMAN_DAYS[day.weekday()]} {day.strftime('%d.%m.')}"
        result.append({"label": label, "meal": meal_name, "ingredients": ingredients})
    return result
