import json
from pathlib import Path

_FILE = Path("data/grocery_completed.json")


def _load() -> list[dict]:
    if not _FILE.exists():
        return []
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def load_completed() -> list[dict]:
    return _load()


def add_completed(task_id: str, content: str, section_id: str | None) -> None:
    items = [i for i in _load() if i["id"] != task_id]
    items.append({"id": task_id, "content": content, "section_id": section_id})
    _save(items)


def remove_completed(task_id: str) -> None:
    _save([i for i in _load() if i["id"] != task_id])
