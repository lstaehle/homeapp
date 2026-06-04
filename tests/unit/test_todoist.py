import pytest
import respx
import httpx


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("TODOIST_API_TOKEN", "fake-token")
    monkeypatch.setenv("TODOIST_PROJECT_NAME", "Einkauf")


def _mock_base(projects=None, sections=None, tasks=None):
    respx.get("https://api.todoist.com/api/v1/projects").mock(
        return_value=httpx.Response(200, json={"results": projects or [{"id": "123", "name": "Einkauf"}]})
    )
    respx.get("https://api.todoist.com/api/v1/sections").mock(
        return_value=httpx.Response(200, json={"results": sections or []})
    )
    respx.get("https://api.todoist.com/api/v1/tasks").mock(
        return_value=httpx.Response(200, json={"results": tasks or []})
    )


@respx.mock
def test_get_restock_items_flat_no_sections():
    _mock_base(tasks=[
        {"id": "1", "content": "Milch", "section_id": None},
        {"id": "2", "content": "Butter", "section_id": None},
    ])
    from app.todoist import get_restock_items
    result = get_restock_items()
    assert len(result) == 1
    assert result[0]["section"] is None
    assert [i["content"] for i in result[0]["items"]] == ["Milch", "Butter"]


@respx.mock
def test_get_restock_items_with_sections():
    _mock_base(
        sections=[{"id": "s1", "name": "Getränke"}, {"id": "s2", "name": "Snacks"}],
        tasks=[
            {"id": "1", "content": "Milch", "section_id": "s1"},
            {"id": "2", "content": "Müsli", "section_id": "s2"},
        ],
    )
    from app.todoist import get_restock_items
    result = get_restock_items()
    sections = {g["section"]: g["items"] for g in result}
    assert "Getränke" in sections
    assert sections["Getränke"][0]["content"] == "Milch"
    assert sections["Snacks"][0]["content"] == "Müsli"


@respx.mock
def test_get_restock_items_filters_by_project():
    respx.get("https://api.todoist.com/api/v1/projects").mock(
        return_value=httpx.Response(200, json={"results": [
            {"id": "123", "name": "Einkauf"},
            {"id": "999", "name": "Arbeit"},
        ]})
    )
    sections_route = respx.get("https://api.todoist.com/api/v1/sections").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    tasks_route = respx.get("https://api.todoist.com/api/v1/tasks").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    from app.todoist import get_restock_items
    get_restock_items()
    assert tasks_route.calls[0].request.url.params["project_id"] == "123"
    assert sections_route.calls[0].request.url.params["project_id"] == "123"


@respx.mock
def test_get_restock_items_empty():
    _mock_base()
    from app.todoist import get_restock_items
    assert get_restock_items() == []


@respx.mock
def test_complete_task_calls_close_endpoint():
    route = respx.post("https://api.todoist.com/api/v1/tasks/42/close").mock(
        return_value=httpx.Response(204)
    )
    from app.todoist import complete_task
    complete_task("42")
    assert route.called
