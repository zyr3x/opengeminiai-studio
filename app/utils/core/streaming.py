from typing import Generator
from app.utils.core.tools import log

STREAM_CHUNK_SIZE = 8192

def stream_file_content(path: str) -> Generator[str, None, None]:
    try:
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk.decode('utf-8', errors='ignore')
    except Exception as e:
        log(f"Error during file content streaming for {path}: {e}")
        yield f"\n[STREAMING ERROR: Failed to stream file content: {e}]\n"

def stream_string(content: str, chunk_size: int = 500) -> Generator[str, None, None]:
    if not content:
        return
    for i in range(0, len(content), chunk_size):
        yield content[i:i + chunk_size]