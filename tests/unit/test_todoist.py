import os

import pytest
import respx
import httpx


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("TODOIST_API_TOKEN", "fake-token")
    monkeypatch.setenv("TODOIST_PROJECT_NAME", "Einkauf")


@respx.mock
def test_get_restock_items_returns_task_names():
    respx.get("https://api.todoist.com/api/v1/projects").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "123", "name": "Einkauf"}]})
    )
    respx.get("https://api.todoist.com/api/v1/tasks").mock(
        return_value=httpx.Response(200, json={"results": [{"content": "Milch"}, {"content": "Butter"}]})
    )

    from app.todoist import get_restock_items
    assert get_restock_items() == ["Milch", "Butter"]


@respx.mock
def test_get_restock_items_filters_by_project():
    respx.get("https://api.todoist.com/api/v1/projects").mock(
        return_value=httpx.Response(200, json={"results": [
            {"id": "123", "name": "Einkauf"},
            {"id": "999", "name": "Arbeit"},
        ]})
    )
    tasks_route = respx.get("https://api.todoist.com/api/v1/tasks").mock(
        return_value=httpx.Response(200, json={"results": [{"content": "Kaffee"}]})
    )

    from app.todoist import get_restock_items
    result = get_restock_items()

    assert tasks_route.calls[0].request.url.params["project_id"] == "123"
    assert result == ["Kaffee"]


@respx.mock
def test_get_restock_items_empty():
    respx.get("https://api.todoist.com/api/v1/projects").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "123", "name": "Einkauf"}]})
    )
    respx.get("https://api.todoist.com/api/v1/tasks").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    from app.todoist import get_restock_items
    assert get_restock_items() == []
