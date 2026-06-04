import os
from todoist_api_python.api import TodoistAPI


def _get_api() -> TodoistAPI:
    return TodoistAPI(os.environ["TODOIST_API_TOKEN"])


def get_restock_items() -> list[str]:
    api = _get_api()
    project_name = os.environ["TODOIST_PROJECT_NAME"]

    projects = api.get_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if not project:
        return []

    tasks = api.get_tasks(project_id=project.id)
    return [task.content for task in tasks]
