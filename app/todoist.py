import os

import httpx

_BASE = "https://api.todoist.com/rest/v2"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['TODOIST_API_TOKEN']}"}


def get_restock_items() -> list[str]:
    project_name = os.environ["TODOIST_PROJECT_NAME"]

    projects = httpx.get(f"{_BASE}/projects", headers=_headers(), timeout=10).raise_for_status().json()
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return []

    tasks = httpx.get(f"{_BASE}/tasks", headers=_headers(), params={"project_id": project["id"]}, timeout=10).raise_for_status().json()
    return [t["content"] for t in tasks]
