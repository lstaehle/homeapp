import os

import httpx

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
        r.raise_for_status()
        raw = r.json().get("items") or []
        return [
            {
                "id": str(t.get("task_id") or t.get("id") or ""),
                "content": t.get("content", ""),
                "section_id": t.get("section_id") or None,
            }
            for t in raw
            if t.get("content")
        ]
    except Exception:
        return []


def get_restock_items() -> list[dict]:
    """Return tasks grouped by section: [{"section": str|None, "items": [...], "completed": [...]}]"""
    project_id = _get_project_id()
    if not project_id:
        return []
    sections = {s["id"]: s["name"] for s in _get("/sections", project_id=project_id)["results"]}
    tasks = _get("/tasks", project_id=project_id)["results"]
    completed = _get_completed_tasks(project_id)

    by_section: dict[str | None, list] = {}
    for t in tasks:
        sid = t.get("section_id") or None
        by_section.setdefault(sid, []).append({"id": t["id"], "content": t["content"]})

    completed_by_section: dict[str | None, list] = {}
    for t in completed:
        sid = t.get("section_id") or None
        completed_by_section.setdefault(sid, []).append({"content": t["content"]})

    # Build result: iterate active sections first, then append completed-only sections
    result = []
    seen: set = set()
    for sid, items in by_section.items():
        seen.add(sid)
        result.append({
            "section": sections.get(sid) if sid else None,
            "items": items,
            "completed": completed_by_section.get(sid, []),
        })
    for sid, items in completed_by_section.items():
        if sid not in seen:
            result.append({
                "section": sections.get(sid) if sid else None,
                "items": [],
                "completed": items,
            })

    result.sort(key=lambda g: (g["section"] is None, g["section"] or ""))
    return result


def complete_task(task_id: str) -> None:
    httpx.post(f"{_BASE}/tasks/{task_id}/close", headers=_headers(), timeout=10).raise_for_status()


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
    project_id = _get_project_id()
    if not project_id:
        return []
    try:
        active = [t["content"] for t in _get("/tasks", project_id=project_id)["results"]]
    except Exception:
        active = []
    completed = [t["content"] for t in _get_completed_tasks(project_id)]  # uses Sync API
    seen: set[str] = set()
    result = []
    for name in active + completed:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            result.append(name)
    result.sort(key=str.casefold)
    return result
