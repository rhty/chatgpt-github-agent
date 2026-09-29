"""Credential-bearing MCP: loopback-only, stateless Streamable HTTP.

The worker is a different container and cannot reach this loopback listener.
Do not expose this port or bind this service to 0.0.0.0.
"""
from starlette.responses import PlainTextResponse
from mcp.server.transport_security import TransportSecuritySettings
from mcp_server import mcp

HOST = '127.0.0.1'
PORT = 8081

mcp.settings.host = HOST
mcp.settings.port = PORT
mcp.settings.streamable_http_path = '/mcp'
mcp.settings.stateless_http = True
mcp.settings.json_response = True
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=['127.0.0.1:*', 'localhost:*'],
    allowed_origins=['http://127.0.0.1:*', 'http://localhost:*'],
)


@mcp.custom_route('/livez', methods=['GET'])
async def livez(request):
    # Liveness only. http_smoke_test.py performs a real MCP handshake.
    return PlainTextResponse('github-agent-mcp-live')


if __name__ == '__main__':
    mcp.run(transport='streamable-http')
