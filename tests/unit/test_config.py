from pathlib import Path

REQUIRED_VARS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID_1",
    "TELEGRAM_CHAT_ID_2",
    "GOOGLE_CREDENTIALS_FILE",
    "GOOGLE_TOKEN_FILE",
    "TODOIST_API_TOKEN",
    "TODOIST_PROJECT_NAME",
]

ROOT = Path(__file__).parent.parent.parent


def test_env_example_contains_all_vars():
    content = (ROOT / ".env.example").read_text()
    for var in REQUIRED_VARS:
        assert var in content, f"Missing required var in .env.example: {var}"


def test_gitignore_excludes_secrets():
    content = (ROOT / ".gitignore").read_text()
    for secret in [".env", "credentials.json", "token.json"]:
        assert secret in content, f"Missing secret in .gitignore: {secret}"
