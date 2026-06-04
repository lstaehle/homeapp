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


def get_restock_items() -> list[dict]:
    """Return tasks grouped by section: [{"section": str|None, "items": [{id, content}]}]"""
    project_id = _get_project_id()
    if not project_id:
        return []
    sections = {s["id"]: s["name"] for s in _get("/sections", project_id=project_id)["results"]}
    tasks = _get("/tasks", project_id=project_id)["results"]

    by_section: dict[str | None, list] = {}
    for t in tasks:
        sid = t.get("section_id") or None
        by_section.setdefault(sid, []).append({"id": t["id"], "content": t["content"]})

    result = []
    for sid, items in by_section.items():
        result.append({"section": sections.get(sid) if sid else None, "items": items})

    result.sort(key=lambda g: (g["section"] is None, g["section"] or ""))
    return result


def complete_task(task_id: str) -> None:
    httpx.post(f"{_BASE}/tasks/{task_id}/close", headers=_headers(), timeout=10).raise_for_status()


def create_task(content: str) -> None:
    project_id = _get_project_id()
    httpx.post(
        f"{_BASE}/tasks",
        headers=_headers(),
        json={"content": content, "project_id": project_id},
        timeout=10,
    ).raise_for_status()
