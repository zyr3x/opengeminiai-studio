import pytest
import os
import json
from app import create_app
from app.config import config

@pytest.fixture
def app():
    app = create_app()
    app.config.update({
        "TESTING": True,
    })
    return app

@pytest.fixture
def client(app):
    return app.test_client()

def test_fs_read_success(client, tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")
    
    # Override project root for safety
    old_root = getattr(config, 'PROJECT_ROOT', None)
    config.PROJECT_ROOT = str(tmp_path)
    
    response = client.get(f'/api/fs/read?path={test_file}')
    assert response.status_code == 200
    assert response.json['content'] == "hello world"
    
    # Restore
    if old_root:
        config.PROJECT_ROOT = old_root

def test_fs_read_traversal(client):
    response = client.get('/api/fs/read?path=/etc/passwd')
    # Because /etc/passwd is outside the project root, it should fail
    assert response.status_code == 403

def test_fs_write_and_revert(client, tmp_path):
    test_file = tmp_path / "mod.txt"
    test_file.write_text("original")
    
    old_root = getattr(config, 'PROJECT_ROOT', None)
    config.PROJECT_ROOT = str(tmp_path)
    
    # Test Write (which should backup)
    response = client.post('/api/fs/write', json={
        "path": str(test_file),
        "content": "modified"
    })
    assert response.status_code == 200
    assert test_file.read_text() == "modified"
    assert os.path.exists(str(test_file) + ".bak")
    
    # Test Revert
    response_revert = client.post('/api/fs/revert', json={
        "path": str(test_file)
    })
    assert response_revert.status_code == 200
    assert test_file.read_text() == "original"
    
    # Restore
    if old_root:
        config.PROJECT_ROOT = old_root
