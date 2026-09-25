import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from constants import Agents


def _parse_command_args(
    environment: Mapping[str, str], variable_name: str, default: list[str]
) -> list[str]:
    raw_value = environment.get(variable_name)
    if raw_value is None:
        return list(default)

    try:
        parsed_value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{variable_name} must contain a JSON list of strings") from exc

    if not isinstance(parsed_value, list) or not all(
        isinstance(value, str) for value in parsed_value
    ):
        raise ValueError(f"{variable_name} must contain a JSON list of strings")
    return parsed_value


def _without_unset_values(values: dict[str, str | None]) -> dict[str, str]:
    return {key: value for key, value in values.items() if value is not None}


def _build_pm2_connection(environment: Mapping[str, str]) -> dict[str, Any]:
    return {
        "command": environment.get("PM2_MCP_COMMAND", "pm2-mcp"),
        "args": _parse_command_args(environment, "PM2_MCP_ARGS_JSON", []),
        "transport": "stdio",
        "env": _without_unset_values(
            {
                key: environment.get(key)
                for key in (
                    "PM2_HOME",
                    "PM2_MCP_HOME",
                    "PM2_MCP_NO_DAEMON",
                    "PM2_SILENT",
                    "PM2_PROGRAMMATIC",
                    "PM2_MCP_DEBUG",
                )
            }
        ),
    }


def build_mcp_connections(
    environment: Mapping[str, str] | None = None,
) -> dict[Agents, dict[str, dict[str, Any]]]:
    """Build MCP connection settings from an explicit environment mapping."""
    env = os.environ if environment is None else environment
    mysql_connection = {
        "command": env.get("MYSQL_MCP_COMMAND", "uvx"),
        "args": _parse_command_args(env, "MYSQL_MCP_ARGS_JSON", ["mdev-mysql-mcp-server"]),
        "transport": "stdio",
        "env": _without_unset_values(
            {
                "MYSQL_HOST": env.get("MYSQL_HOST", "localhost"),
                "MYSQL_PORT": env.get("MYSQL_PORT", "3306"),
                "MYSQL_USER": env.get("MYSQL_USER", "root"),
                "MYSQL_PASSWORD": env.get("MYSQL_PASSWORD"),
                "MYSQL_DATABASE": env.get("MYSQL_DATABASE"),
            }
        ),
    }
    elasticsearch_base = {
        "command": env.get("ELASTICSEARCH_MCP_COMMAND", "uvx"),
        "args": _parse_command_args(
            env,
            "ELASTICSEARCH_MCP_ARGS_JSON",
            ["elasticsearch-mcp-server"],
        ),
        "transport": "stdio",
    }
    elasticsearch_environment = _without_unset_values(
        {
            "ELASTICSEARCH_HOSTS": env.get("ELASTICSEARCH_HOSTS", "https://localhost:9200"),
            "ELASTICSEARCH_USERNAME": env.get("ELASTICSEARCH_USERNAME"),
            "ELASTICSEARCH_PASSWORD": env.get("ELASTICSEARCH_PASSWORD"),
            "ELASTICSEARCH_VERIFY_CERTS": env.get("ELASTICSEARCH_VERIFY_CERTS", "false"),
        }
    )
    pm2_connection = _build_pm2_connection(env)
    investigator_connections = {
        "mysql": mysql_connection,
        "pm2": pm2_connection,
        "elasticsearch-mcp-server": {
            **elasticsearch_base,
            "env": {
                **elasticsearch_environment,
                "DISABLE_HIGH_RISK_OPERATIONS": "true",
            },
        },
    }
    executor_connections = {
        "mysql": mysql_connection,
        "pm2": pm2_connection,
        "memory": {
            "command": sys.executable,
            "args": [str(Path(__file__).parent / "server/memory.py")],
            "transport": "stdio",
        },
        "elasticsearch-mcp-server": {
            **elasticsearch_base,
            "env": {
                **elasticsearch_environment,
                "DISABLE_HIGH_RISK_OPERATIONS": "false",
            },
        },
    }
    return {
        Agents.LOG_INVESTIGATOR: investigator_connections,
        Agents.MITIGATION_ENGINEER: investigator_connections,
        Agents.MITIGATION_EXECUTOR: executor_connections,
    }


def create_mcp_clients(
    connections: dict[Agents, dict[str, dict[str, Any]]],
) -> dict[Agents, MultiServerMCPClient]:
    """Create one read-only client and one mutation-capable executor client."""
    read_only_client = MultiServerMCPClient(connections[Agents.LOG_INVESTIGATOR])
    executor_client = MultiServerMCPClient(connections[Agents.MITIGATION_EXECUTOR])
    return {
        Agents.LOG_INVESTIGATOR: read_only_client,
        Agents.MITIGATION_ENGINEER: read_only_client,
        Agents.MITIGATION_EXECUTOR: executor_client,
    }


mcp_connections = build_mcp_connections()
mcp_clients = create_mcp_clients(mcp_connections)

# Compatibility aliases for code that imports the configured clients directly.
log_investigator_client = mcp_clients[Agents.LOG_INVESTIGATOR]
mitigation_executor_client = mcp_clients[Agents.MITIGATION_EXECUTOR]


async def get_tools(agent: Agents, server_name: str | None = None):
    client = mcp_clients.get(agent)
    if client is None:
        return None
    return await client.get_tools(server_name=server_name)
