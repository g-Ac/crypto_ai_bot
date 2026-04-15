"""Tests for Pip-Boy routes and SSE endpoint."""
import pytest


@pytest.fixture
def client():
    """Flask test client for dashboard."""
    import dashboard_server
    dashboard_server.app.config["TESTING"] = True
    with dashboard_server.app.test_client() as c:
        yield c


class TestPipBoyPages:
    def test_pip_status_page(self, client):
        resp = client.get("/pip/status")
        assert resp.status_code == 200
        assert b"GABRIEL" in resp.data

    def test_pip_trades_page(self, client):
        resp = client.get("/pip/trades")
        assert resp.status_code == 200

    def test_pip_analysis_page(self, client):
        resp = client.get("/pip/analysis")
        assert resp.status_code == 200

    def test_pip_logs_page(self, client):
        resp = client.get("/pip/logs")
        assert resp.status_code == 200

    def test_pip_system_page(self, client):
        resp = client.get("/pip/system")
        assert resp.status_code == 200

    def test_pip_root_redirects_to_status(self, client):
        resp = client.get("/pip/")
        assert resp.status_code in (200, 302)


class TestPipBoyPartials:
    def test_partial_ticker(self, client):
        resp = client.get("/pip/partial/ticker")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_partial_kpis(self, client):
        resp = client.get("/pip/partial/kpis")
        assert resp.status_code == 200

    def test_partial_positions(self, client):
        resp = client.get("/pip/partial/positions")
        assert resp.status_code == 200


class TestSSELogs:
    def test_stream_logs_returns_event_stream(self, client):
        resp = client.get("/stream/logs?source=main&lines=5")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
