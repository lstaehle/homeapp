import os
from unittest.mock import MagicMock, patch

import pytest


def _make_project(name: str, project_id: str = "123") -> MagicMock:
    p = MagicMock()
    p.name = name
    p.id = project_id
    return p


def _make_task(content: str, project_id: str = "123") -> MagicMock:
    t = MagicMock()
    t.content = content
    t.project_id = project_id
    return t


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("TODOIST_API_TOKEN", "fake-token")
    monkeypatch.setenv("TODOIST_PROJECT_NAME", "Einkauf")


@patch("app.todoist.TodoistAPI")
def test_get_restock_items_returns_task_names(mock_api_cls):
    api = MagicMock()
    api.get_projects.return_value = [_make_project("Einkauf", "123")]
    api.get_tasks.return_value = [
        _make_task("Milch"),
        _make_task("Butter"),
    ]
    mock_api_cls.return_value = api

    from app.todoist import get_restock_items

    result = get_restock_items()

    assert result == ["Milch", "Butter"]


@patch("app.todoist.TodoistAPI")
def test_get_restock_items_filters_by_project(mock_api_cls):
    api = MagicMock()
    api.get_projects.return_value = [
        _make_project("Einkauf", "123"),
        _make_project("Arbeit", "999"),
    ]
    api.get_tasks.return_value = [_make_task("Kaffee", "123")]
    mock_api_cls.return_value = api

    from app.todoist import get_restock_items

    result = get_restock_items()

    api.get_tasks.assert_called_once_with(project_id="123")
    assert result == ["Kaffee"]


@patch("app.todoist.TodoistAPI")
def test_get_restock_items_empty(mock_api_cls):
    api = MagicMock()
    api.get_projects.return_value = [_make_project("Einkauf", "123")]
    api.get_tasks.return_value = []
    mock_api_cls.return_value = api

    from app.todoist import get_restock_items

    assert get_restock_items() == []
