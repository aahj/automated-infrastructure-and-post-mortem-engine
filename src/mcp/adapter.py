import os
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from constants import Agents

log_investigator_client = MultiServerMCPClient(
    {
        "mysql": {
            "command": "uvx",
            "args": ["mdev-mysql-mcp-server"],
            "transport": "stdio",
            "env": {
                "MYSQL_HOST": os.getenv("MYSQL_HOST", "localhost"),
                "MYSQL_PORT": os.getenv("MYSQL_PORT", "3306"),
                "MYSQL_USER": os.getenv("MYSQL_USER", "root"),
                "MYSQL_PASSWORD": os.getenv("MYSQL_PASSWORD"),
                "MYSQL_DATABASE": os.getenv("MYSQL_DATABASE"),
            },
        }
    }
)

mitigation_engineer_client = MultiServerMCPClient(
    {
        "mysql": {
            "command": "uvx",
            "args": ["mdev-mysql-mcp-server"],
            "transport": "stdio",
            "env": {
                "MYSQL_HOST": os.getenv("MYSQL_HOST", "localhost"),
                "MYSQL_PORT": os.getenv("MYSQL_PORT", "3306"),
                "MYSQL_USER": os.getenv("MYSQL_USER", "root"),
                "MYSQL_PASSWORD": os.getenv("MYSQL_PASSWORD"),
                "MYSQL_DATABASE": os.getenv("MYSQL_DATABASE"),
            },
        },
        "memory": {
            "command": "python",
            "args": [str(Path(__file__).parent / "server/memory.py")],
            "transport": "stdio",
        },
    }
)


async def get_tools(agent: Agents):
    match agent:
        case Agents.LOG_INVESTIGATOR:
            return await log_investigator_client.get_tools()
        case Agents.MITIGATION_ENGINEER:
            return await mitigation_engineer_client.get_tools()
        case _:
            return None
