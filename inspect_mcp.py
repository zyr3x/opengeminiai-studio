import asyncio
from app import create_app
from app.core.mcp_server import mcp

async def main():
    app = create_app()
    tools = await mcp.list_tools()
    print("Tools list:")
    for t in tools:
        print(t)

asyncio.run(main())
