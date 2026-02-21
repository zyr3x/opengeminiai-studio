from fastmcp import FastMCP

# This function might be auto-discovered or registered differently depending on how we expose the FastMCP instance,
# For now, we will assume a global MCP instance in app.core.mcp_server

from app.core.mcp_server import mcp

@mcp.tool()
async def add_numbers(a: int, b: int) -> int:
    """Adds two integers together."""
    return a + b
