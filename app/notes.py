import json
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Zurich")
_FILE = Path("data/notes.json")


def _load() -> list[dict]:
    if not _FILE.exists():
        return []
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(notes: list[dict]) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")


def get_notes() -> list[dict]:
    return _load()


def add_note(text: str, author: str = "") -> dict:
    notes = _load()
    note = {
        "id": str(uuid.uuid4())[:8],
        "text": text,
        "author": author,
        "created_at": datetime.now(TZ).strftime("%d.%m. %H:%M"),
    }
    notes.append(note)
    _save(notes)
    return note


def delete_note(note_id: str) -> None:
    notes = [n for n in _load() if n["id"] != note_id]
    _save(notes)
