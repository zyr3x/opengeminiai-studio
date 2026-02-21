import pytest
from pydantic import ValidationError
from app.schemas.requests import ChatRequestSchema
from app.schemas.responses import ChatResponseSchema

def test_chat_request_schema_valid():
    valid_data = {
        "model": "gemini-2.5-flash",
        "messages": [
            {"role": "user", "content": "Hello"}
        ],
        "temperature": 0.7
    }
    schema = ChatRequestSchema.model_validate(valid_data)
    assert schema.model == "gemini-2.5-flash"
    assert len(schema.messages) == 1
    assert schema.messages[0].role == "user"
    assert schema.temperature == 0.7

def test_chat_request_schema_invalid():
    invalid_data = {
        "model": "gemini-test",
        "messages": [] # Messages length < 1
    }
    with pytest.raises(ValidationError):
        ChatRequestSchema.model_validate(invalid_data)

def test_chat_response_schema():
    response_data = {
        "id": "chatcmpl-123",
        "created": 1677652288,
        "model": "gemini",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hi there!"
            },
            "finish_reason": "stop"
        }]
    }
    schema = ChatResponseSchema.model_validate(response_data)
    assert schema.id == "chatcmpl-123"
    assert schema.choices[0].finish_reason == "stop"
