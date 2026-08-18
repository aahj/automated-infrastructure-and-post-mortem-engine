import os
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from constants import Agents

log_investigator_client = MultiServerMCPClient(
    {
        "mysql": {
            # "command": "uvx",
            # "args": ["mdev-mysql-mcp-server"],
            "command": "D:\\Projects\\mysql-mcp-server\\.venv\\Scripts\\mdev-mysql-mcp-server.exe",
            "args": [],
            "transport": "stdio",
            "env": {
                "MYSQL_HOST": os.getenv("MYSQL_HOST", "localhost"),
                "MYSQL_PORT": os.getenv("MYSQL_PORT", "3306"),
                "MYSQL_USER": os.getenv("MYSQL_USER", "root"),
                "MYSQL_PASSWORD": os.getenv("MYSQL_PASSWORD"),
                "MYSQL_DATABASE": os.getenv("MYSQL_DATABASE"),
            },
        },
        "elasticsearch-mcp-server": {
            "command": "uvx",
            "args": ["elasticsearch-mcp-server"],
            "transport": "stdio",
            "env": {
                "ELASTICSEARCH_HOSTS": os.getenv("ELASTICSEARCH_HOSTS", "https://localhost:9200"),
                "ELASTICSEARCH_USERNAME": os.getenv("ELASTICSEARCH_USERNAME"),
                "ELASTICSEARCH_PASSWORD": os.getenv("ELASTICSEARCH_PASSWORD"),
                "DISABLE_HIGH_RISK_OPERATIONS": "true",
                "ELASTICSEARCH_VERIFY_CERTS": os.getenv("ELASTICSEARCH_VERIFY_CERTS", "false"),
            },
        },
    }
)

mitigation_executor_client = MultiServerMCPClient(
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
        "elasticsearch-mcp-server": {
            "command": "uvx",
            "args": ["elasticsearch-mcp-server"],
            "transport": "stdio",
            "env": {
                "ELASTICSEARCH_HOSTS": os.getenv("ELASTICSEARCH_HOSTS", "https://localhost:9200"),
                "ELASTICSEARCH_USERNAME": os.getenv("ELASTICSEARCH_USERNAME"),
                "ELASTICSEARCH_PASSWORD": os.getenv("ELASTICSEARCH_PASSWORD"),
                "DISABLE_HIGH_RISK_OPERATIONS": "false",
                "ELASTICSEARCH_VERIFY_CERTS": os.getenv("ELASTICSEARCH_VERIFY_CERTS", "false"),
            },
        },
    }
)


async def get_tools(agent: Agents):
    match agent:
        case Agents.LOG_INVESTIGATOR:
            return await log_investigator_client.get_tools()
        case Agents.MITIGATION_EXECUTOR:
            return await mitigation_executor_client.get_tools()
        case _:
            return None
