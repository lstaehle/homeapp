"""
System tests — require Docker and a valid .env in the project root.
Run with: make test-system
"""
import subprocess
import time

import pytest
import httpx

BASE_URL = "http://localhost:8000"
COMPOSE = ["docker", "compose"]


def _docker_available() -> bool:
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


skip_no_docker = pytest.mark.skipif(not _docker_available(), reason="Docker not available")


@pytest.fixture(scope="module", autouse=True)
def compose_stack():
    subprocess.run([*COMPOSE, "down", "--remove-orphans"], capture_output=True)
    yield
    subprocess.run([*COMPOSE, "down", "--remove-orphans"], capture_output=True)


@skip_no_docker
def test_container_builds():
    result = subprocess.run([*COMPOSE, "build"], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


@skip_no_docker
def test_container_starts():
    subprocess.run([*COMPOSE, "up", "-d"], capture_output=True, check=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        result = subprocess.run(
            [*COMPOSE, "ps", "--format", "json"],
            capture_output=True, text=True
        )
        if "running" in result.stdout.lower() or "Up" in result.stdout:
            return
        time.sleep(1)
    pytest.fail("Container did not reach running state within 30 seconds")


@skip_no_docker
def test_health_endpoint():
    time.sleep(5)
    r = httpx.get(f"{BASE_URL}/health", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@skip_no_docker
def test_dashboard_loads():
    r = httpx.get(f"{BASE_URL}/", timeout=10)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@skip_no_docker
def test_api_endpoints_reachable():
    for path in ("/api/today", "/api/week", "/api/grocery"):
        r = httpx.get(f"{BASE_URL}{path}", timeout=10)
        assert r.status_code == 200, f"{path} returned {r.status_code}"
