import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Server settings
    SERVER_HOST: str = Field(default="127.0.0.1")
    SERVER_PORT: int = Field(default=8080)
    SECRET_KEY: str = Field(default="your-secret-key-here-change-this-to-random-string")

    # App Features
    ASYNC_MODE: bool = Field(default=True)
    DEBUG_MODE: bool = Field(default=False)
    
    # Internal paths
    DATA_DIR: str = Field(default="./var")

settings = Settings()
