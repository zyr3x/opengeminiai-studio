import pytest
from app import create_app

@pytest.fixture
def app():
    app = create_app()
    app.config.update({"TESTING": True})
    yield app

@pytest.fixture
def client(app):
    return app.test_client()

def test_web_ui_root(client):
    """Test the main index route for the web UI."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"<!DOCTYPE html>" in response.data

def test_web_ui_models_api(client):
    """Test the internal /api/models UI route, which is different from proxy /v1/models"""
    response = client.get("/api/models")
    # Might be 401 if API key isn't mocked/configured, but should return JSON instead of crashing
    assert response.status_code in [200, 401]
    if response.status_code == 200:
        assert isinstance(response.json, dict)
        assert "object" in response.json
