import pytest
from app import create_app

@pytest.fixture
def app():
    app = create_app()
    app.config.update({
        "TESTING": True,
    })
    yield app

@pytest.fixture
def client(app):
    return app.test_client()

def test_ping(client):
    """Test the core application ping endpoint."""
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json["status"] == "ok"

def test_demo_hello(client):
    """Test the asynchronously autoloaded demo endpoint."""
    response = client.get("/demo/hello")
    # For async endpoints in Flask 3+, the test client handles the loop if the route is defined correctly.
    assert response.status_code == 200
    assert response.json["message"] == "Hello from asynchronously autoloaded module!"
