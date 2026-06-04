import json
from datetime import date, timedelta
from pathlib import Path

_PLAN_FILE = Path("data/meals_plan.json")
_LIST_FILE = Path("data/meals_list.json")
_SENT_FILE = Path("data/ingredients_sent.json")

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
    # Migrate from old flat-string format
    if data and isinstance(data[0], str):
        return [{"name": m, "ingredients": []} for m in data]
    return data


def _save_list(meals: list[dict]) -> None:
    _LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LIST_FILE.write_text(json.dumps(meals, ensure_ascii=False, indent=2))


def _load_sent() -> list[str]:
    if not _SENT_FILE.exists():
        return []
    return json.loads(_SENT_FILE.read_text())


def _save_sent(sent: list[str]) -> None:
    _SENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SENT_FILE.write_text(json.dumps(sent))


# ---------------------------------------------------------------------------
# Meal plan
# ---------------------------------------------------------------------------

def get_plan() -> dict:
    return _load_plan()


def set_meal(day: date, meal: str) -> None:
    plan = _load_plan()
    plan[day.isoformat()] = meal
    _save_plan(plan)
    # Reset sent flag so the new meal's ingredients appear as pending again
    sent = _load_sent()
    if day.isoformat() in sent:
        sent.remove(day.isoformat())
        _save_sent(sent)


def delete_meal(day: date) -> None:
    plan = _load_plan()
    plan.pop(day.isoformat(), None)
    _save_plan(plan)


# ---------------------------------------------------------------------------
# Meal list & ingredients
# ---------------------------------------------------------------------------

def get_meal_list() -> list[dict]:
    """Returns [{"name": str, "ingredients": [str]}]"""
    return _load_list()


def get_meal_names() -> list[str]:
    return [m["name"] for m in _load_list()]


def add_to_meal_list(meal: str) -> None:
    meals = _load_list()
    if not any(m["name"] == meal for m in meals):
        meals.append({"name": meal, "ingredients": []})
        _save_list(meals)


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
    Returns ingredients from planned meals (today + next 6 days)
    that haven't been sent to Todoist yet.
    [{"date": "YYYY-MM-DD", "label": "Fr 05.06.", "meal": str, "ingredients": [str]}]
    """
    plan = _load_plan()
    sent = _load_sent()
    meals_map = {m["name"]: m["ingredients"] for m in _load_list()}
    today = date.today()

    result = []
    for i in range(7):
        day = today + timedelta(days=i)
        day_str = day.isoformat()
        if day_str in sent:
            continue
        meal_name = plan.get(day_str)
        if not meal_name:
            continue
        ingredients = meals_map.get(meal_name, [])
        if not ingredients:
            continue
        label = f"{'Heute' if i == 0 else GERMAN_DAYS[day.weekday()]} {day.strftime('%d.%m.')}"
        result.append({
            "date": day_str,
            "label": label,
            "meal": meal_name,
            "ingredients": ingredients,
        })
    return result


def mark_ingredients_sent(day_str: str) -> None:
    sent = _load_sent()
    if day_str not in sent:
        sent.append(day_str)
        _save_sent(sent)
