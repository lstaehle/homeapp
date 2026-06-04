import os

import httpx

_BASE = "https://api.todoist.com/api/v1"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['TODOIST_API_TOKEN']}"}


def _get(path: str, **params) -> dict:
    r = httpx.get(f"{_BASE}{path}", headers=_headers(), params=params or None, timeout=10)
    r.raise_for_status()
    return r.json()


def get_restock_items() -> list[dict]:
    project_name = os.environ["TODOIST_PROJECT_NAME"]

    projects = _get("/projects")["results"]
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return []

    tasks = _get("/tasks", project_id=project["id"])["results"]
    return [{"id": t["id"], "content": t["content"]} for t in tasks]


def complete_task(task_id: str) -> None:
    httpx.post(f"{_BASE}/tasks/{task_id}/close", headers=_headers(), timeout=10).raise_for_status()
