from typing import Generator
import os
import json
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

def async_to_sync_generator(async_gen):
    """
    Bridge an async generator to a sync generator.
    Useful for Flask Response in a WSGI environment wrapped by ASGI.
    """
    import asyncio
    
    def wrapper():
        # Create a new event loop for this thread to consume the async generator
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Get the asynchronous iterator
            it = async_gen.__aiter__()
            
            while True:
                try:
                    # Advance the async generator
                    chunk = loop.run_until_complete(it.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
                except Exception as e:
                    log(f"Error in async_to_sync_generator: {e}")
                    yield f" [STREAM ERROR: {e}] "
                    break
        finally:
            loop.close()
            
    return wrapper()