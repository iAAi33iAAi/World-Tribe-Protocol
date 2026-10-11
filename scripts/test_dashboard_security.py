"""Regression tests for World Tribe's local dashboard security boundary."""
import json
import sys
import threading
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_server import DashboardHandler, public_deployment_summary


@pytest.fixture
def dashboard_server(tmp_path):
    handler = partial(
        DashboardHandler,
        config_path=tmp_path / "deployment.json",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(server, method, path):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    connection.request(method, path)
    response = connection.getresponse()
    result = (response.status, response.read())
    connection.close()
    return result


def test_dashboard_only_serves_public_entrypoint(dashboard_server):
    status, body = _request(dashboard_server, "GET", "/")
    assert status == 200
    assert b"World Tribe OS" in body

    status, body = _request(dashboard_server, "GET", "/index.html")
    assert status == 200
    assert b"World Tribe OS" in body


@pytest.mark.parametrize(
    "path",
    [
        "/WorldTribe.sol",
        "/safeguard-internal",
        "/config/deployment.json",
        "/build/WorldTribe_compiled.json",
        "/scripts/dashboard_server.py",
        "/.gitignore",
        "/../safeguard-internal",
    ],
)
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_dashboard_denies_repository_file_reads(dashboard_server, path, method):
    status, _body = _request(dashboard_server, method, path)
    assert status == 404


def test_public_deployment_summary_never_returns_provider_url():
    private_endpoint = "https://rpc.example.invalid/v3/private-token"
    deployment = {
        "contract_address": "0x1234567890123456789012345678901234567890",
        "provider_url": private_endpoint,
        "deployment_block": 123,
        "generated_at": "2026-10-11T00:00:00+00:00",
    }

    public = public_deployment_summary(deployment)
    serialized = json.dumps(public)

    assert public["provider_configured"] is True
    assert "provider_url" not in public
    assert private_endpoint not in serialized
    assert public["contract_address"] == deployment["contract_address"]


def test_public_deployment_summary_marks_missing_provider():
    deployment = {
        "contract_address": "0x1234567890123456789012345678901234567890",
        "provider_url": "",
        "deployment_block": 0,
        "generated_at": None,
    }
    public = public_deployment_summary(deployment)
    assert public["provider_configured"] is False
    assert "provider_url" not in public
