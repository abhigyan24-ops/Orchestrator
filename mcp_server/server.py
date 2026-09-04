from dotenv import load_dotenv
load_dotenv()

from fastmcp import FastMCP

# Create the main FastMCP server instance
mcp = FastMCP("MultiAgentOrchestrator")

# We import tools here so they register with the mcp instance
import mcp_server.tools

if not hasattr(mcp, "streamable_http_app"):
    mcp.streamable_http_app = lambda path="/", **kwargs: mcp.http_app(path=path, transport="streamable-http", **kwargs)

if __name__ == "__main__":
    mcp.run()

