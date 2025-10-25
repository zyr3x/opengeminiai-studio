"""
Module for incremental streaming of tool results.

Instead of waiting for the full tool result, we stream the results
as they are received to improve UX and reduce perceived latency.
"""
from typing import Generator
from .utils import log

# Chunk size for streaming file content (e.g., 8KB)
STREAM_CHUNK_SIZE = 8192

def stream_file_content(path: str) -> Generator[str, None, None]:
    """
    Reads a file in chunks and yields the content as a generator of strings.
    Assumes path has already been resolved and checked for safety/existence.
    """
    try:
        # Use 'rb' for robust reading, then decode per chunk
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                # Decode chunk to text, errors='ignore' is used for robustness
                yield chunk.decode('utf-8', errors='ignore')

    except Exception as e:
        log(f"Error during file content streaming for {path}: {e}")
        # Yield the error message instead of raising
        yield f"\n[STREAMING ERROR: Failed to stream file content: {e}]\n"

def stream_string(content: str, chunk_size: int = 500) -> Generator[str, None, None]:
    """
    Converts a large string into a generator that yields smaller chunks.
    """
    if not content:
        return
    for i in range(0, len(content), chunk_size):
        yield content[i:i + chunk_size]