"""Real stdio MCP initialize/list_tools check, after the image has its SDK installed."""
import asyncio
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params=StdioServerParameters(command='/opt/venv/bin/python',args=['/opt/control/mcp_server.py'],env=dict(os.environ))
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as s:
            await s.initialize()
            tools=await s.list_tools()
            names={t.name for t in tools.tools}
            expected={'system_status','start_task','publish_pr','get_feedback','reply','get_job','ci_log'}
            if not expected.issubset(names): raise RuntimeError('Missing expected tools')
            print('MCP_STDIO_CHECK_OK',len(names),'tools')
asyncio.run(main())
