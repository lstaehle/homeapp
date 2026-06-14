import json
from datetime import datetime, timedelta
from pathlib import Path

_FILE = Path("data/grocery_completed.json")
_EXPIRY_DAYS = 30


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


def _unexpired(items: list[dict]) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=_EXPIRY_DAYS)).isoformat()
    return [i for i in items if i.get("completed_at", "9999") >= cutoff]


def load_completed(active_ids: set[str] | None = None) -> list[dict]:
    """Return locally stored completed items, dropping expired ones and any
    that have since been reopened in Todoist (present in active_ids)."""
    items = _unexpired(_load())
    if active_ids:
        items = [i for i in items if i["id"] not in active_ids]
    _save(items)
    return items


def add_completed(task_id: str, content: str, section_id: str | None) -> None:
    items = [i for i in _load() if i["id"] != task_id]
    items.append({
        "id": task_id,
        "content": content,
        "section_id": section_id,
        "completed_at": datetime.utcnow().isoformat(),
    })
    _save(items)


def remove_completed(task_id: str) -> None:
    _save([i for i in _load() if i["id"] != task_id])
