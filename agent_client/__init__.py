"""Agent client package — shared HTTP client for CLI and MCP layers.

Both the pptctl CLI and the MCP server use this client to call the Agent API.
Neither layer should directly access the database or project files.
"""

from agent_client.client import AgentClient
from agent_client.polling import poll_operation, PollConfig

__all__ = ["AgentClient", "poll_operation", "PollConfig"]
