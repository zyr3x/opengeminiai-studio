from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union

class ChatChoiceModel(BaseModel):
    index: int
    message: Dict[str, Any]
    finish_reason: Optional[str] = None

class ChatResponseSchema(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoiceModel]
    usage: Optional[Dict[str, int]] = None
