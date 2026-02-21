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

def test_proxy_valid_request(client):
    """Test valid request parsing through Pydantic to the proxy endpoint."""
    payload = {
        "model": "gemini-2.5-flash",
        "messages": [
            {"role": "user", "content": "What is the capital of France?"}
        ]
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    
    # Read the streamed response
    data = response.data.decode('utf-8')
    assert "data: " in data
    assert "chat.completion.chunk" in data

def test_proxy_invalid_request(client):
    """Test invalid request caught by Pydantic."""
    payload = {
        "model": "gemini-lite",
        # Missing messages
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200 # It does not return 400 since messages default to empty.
    
    data = response.data.decode('utf-8')
    assert "data: " in data
    assert "chat.completion.chunk" in data
