import logging
import os

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.todoist.com/api/v1"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['TODOIST_API_TOKEN']}"}


def _get(path: str, **params) -> dict:
    r = httpx.get(f"{_BASE}{path}", headers=_headers(), params=params or None, timeout=10)
    r.raise_for_status()
    return r.json()


def _get_project_id() -> str | None:
    project_name = os.environ["TODOIST_PROJECT_NAME"]
    projects = _get("/projects")["results"]
    project = next((p for p in projects if p["name"] == project_name), None)
    return project["id"] if project else None


def _get_completed_tasks(project_id: str) -> list[dict]:
    """Fetches completed tasks via Sync API. Returns [] on any error."""
    try:
        r = httpx.get(
            "https://api.todoist.com/sync/v9/items/completed/get_all",
            headers=_headers(),
            params={"project_id": project_id, "limit": 200},
            timeout=10,
        )
        logger.info("completed tasks HTTP %d: %s", r.status_code, r.text[:500])
        r.raise_for_status()
        raw = r.json().get("items") or []
        logger.info("completed tasks fetched: %d items", len(raw))
        if raw:
            logger.info("completed task sample: %s", raw[0])
        return [
            {
                "id": str(t.get("task_id") or t.get("id") or ""),
                "content": t.get("content", ""),
                "section_id": str(t["section_id"]) if t.get("section_id") else None,
            }
            for t in raw
            if t.get("content")
        ]
    except Exception as exc:
        logger.error("_get_completed_tasks failed: %s", exc)
        return []


def get_restock_items() -> list[dict]:
    """Return tasks grouped by section: [{"section": str|None, "items": [...], "completed": [...]}]"""
    from app.grocery_store import load_completed
    project_id = _get_project_id()
    if not project_id:
        return []
    sections = {str(s["id"]): s["name"] for s in _get("/sections", project_id=project_id)["results"]}
    tasks = _get("/tasks", project_id=project_id)["results"]
    completed = load_completed()
    logger.info("sections: %s", sections)

    def _sid(raw) -> str | None:
        return str(raw) if raw else None

    by_section: dict[str | None, list] = {}
    for t in tasks:
        sid = _sid(t.get("section_id"))
        by_section.setdefault(sid, []).append({"id": t["id"], "content": t["content"], "section_id": sid})
        logger.debug("task %r section_id=%r → sid=%r", t["content"], t.get("section_id"), sid)

    completed_by_section: dict[str | None, list] = {}
    for t in completed:
        sid = _sid(t.get("section_id"))
        completed_by_section.setdefault(sid, []).append({"id": t["id"], "content": t["content"]})

    # Build result: iterate active sections first, then append completed-only sections
    result = []
    seen: set = set()
    for sid, items in by_section.items():
        seen.add(sid)
        section_name = sections.get(sid) if sid else None
        result.append({
            "section": section_name,
            "items": items,
            "completed": completed_by_section.get(sid, []),
        })
    for sid, items in completed_by_section.items():
        if sid not in seen:
            section_name = sections.get(sid) if sid else None
            result.append({
                "section": section_name,
                "items": [],
                "completed": items,
            })

    result.sort(key=lambda g: (g["section"] is None, g["section"] or ""))
    logger.info(
        "get_restock_items: %d groups — %s",
        len(result),
        [(g["section"], len(g["items"]), len(g["completed"])) for g in result],
    )
    return result


def complete_task(task_id: str) -> None:
    httpx.post(f"{_BASE}/tasks/{task_id}/close", headers=_headers(), timeout=10).raise_for_status()


def reopen_task(task_id: str) -> None:
    httpx.post(f"{_BASE}/tasks/{task_id}/reopen", headers=_headers(), timeout=10).raise_for_status()


def get_sections() -> list[dict]:
    """Returns [{"id": str, "name": str}] for the grocery project."""
    project_id = _get_project_id()
    if not project_id:
        return []
    results = _get("/sections", project_id=project_id)["results"]
    return [{"id": s["id"], "name": s["name"]} for s in results]


def create_task(content: str, section_id: str | None = None) -> None:
    project_id = _get_project_id()
    body: dict = {"content": content, "project_id": project_id}
    if section_id:
        body["section_id"] = section_id
    httpx.post(f"{_BASE}/tasks", headers=_headers(), json=body, timeout=10).raise_for_status()


def get_all_task_names() -> list[str]:
    """Returns deduplicated sorted task names (active + completed) for the ingredient picker."""
    from app.grocery_store import load_completed
    project_id = _get_project_id()
    if not project_id:
        return []
    try:
        active = [t["content"] for t in _get("/tasks", project_id=project_id)["results"]]
    except Exception:
        active = []
    completed_names = [t["content"] for t in load_completed()]
    seen: set[str] = set()
    result = []
    for name in active + completed_names:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            result.append(name)
    result.sort(key=str.casefold)
    return result
