from pydantic import BaseModel, Field, conlist
from typing import List, Optional, Dict, Any, Union

class MessageModel(BaseModel):
    role: str = Field(..., description="The role of the message (user, assistant, system).")
    content: str = Field(..., description="The content of the message.")

class ToolCallModel(BaseModel):
    name: str
    arguments: Dict[str, Any]

class ChatRequestSchema(BaseModel):
    model: str = Field(..., description="The language model to use.")
    messages: conlist(MessageModel, min_length=1) = Field(..., description="List of messages in the conversation.")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1)
    tools: Optional[List[Dict[str, Any]]] = Field(None, description="Array of tools available to the model")
    stream: Optional[bool] = Field(False)
