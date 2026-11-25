import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from _mcp.adapter import build_mcp_connections, create_mcp_clients, get_tools
from constants import Agents


class PM2MCPConfigurationTests(unittest.TestCase):
    def test_pm2_http_configuration_uses_distinct_read_and_write_bearer_tokens(self):
        environment = {
            "PM2_MCP_URL": "http://pm2-host:8486/mcp",
            "PM2_MCP_READ_TOKEN": "read-secret",
            "PM2_MCP_WRITE_TOKEN": "write-secret",
        }

        connections = build_mcp_connections(environment)

        read = connections[Agents.LOG_INVESTIGATOR]["pm2"]
        write = connections[Agents.MITIGATION_EXECUTOR]["pm2"]
        self.assertEqual(read["url"], "http://pm2-host:8486/mcp")
        self.assertEqual(read["headers"], {"Authorization": "Bearer read-secret"})
        self.assertEqual(write["headers"], {"Authorization": "Bearer write-secret"})
        self.assertIsNot(read, write)
    def test_pm2_stdio_fallback_uses_command_arguments_and_agent_access(self):
        environment = {
            "PM2_MCP_TRANSPORT": "stdio",
            "PM2_MCP_COMMAND": "node",
            "PM2_MCP_ARGS_JSON": '["dist/index.js"]',
            "PM2_HOME": "C:/pm2-test",
            "PM2_MCP_START_TARGETS_JSON": '{"api":{"script":"api.js"}}',
        }

        connections = build_mcp_connections(environment)
        read = connections[Agents.LOG_INVESTIGATOR]["pm2"]
        write = connections[Agents.MITIGATION_EXECUTOR]["pm2"]

        self.assertEqual(read["transport"], "stdio")
        self.assertEqual(read["command"], "node")
        self.assertEqual(read["args"], ["dist/index.js"])
        self.assertEqual(read["env"]["PM2_HOME"], "C:/pm2-test")
        self.assertEqual(read["env"]["PM2_MCP_STDIO_ACCESS"], "read")
        self.assertEqual(
            read["env"]["PM2_MCP_START_TARGETS_JSON"],
            environment["PM2_MCP_START_TARGETS_JSON"],
        )
        self.assertEqual(write["env"]["PM2_MCP_STDIO_ACCESS"], "write")
        self.assertNotIn("headers", read)
        self.assertNotIn("headers", write)
    def test_pm2_stdio_fallback_defaults_to_owned_server_entrypoint(self):
        connection = build_mcp_connections({"PM2_MCP_TRANSPORT": "stdio"})[
            Agents.LOG_INVESTIGATOR
        ]["pm2"]
        server_directory = Path(__file__).parents[3] / "pm2-mcp"

        self.assertEqual(connection["command"], "node")
        self.assertEqual(
            connection["args"], [str(server_directory / "dist" / "index.js")]
        )
        self.assertEqual(connection["cwd"], str(server_directory))
        self.assertEqual(connection["env"]["PM2_MCP_STDIO_ACCESS"], "read")
    def test_pm2_rejects_unknown_transport(self):
        with self.assertRaisesRegex(ValueError, "PM2_MCP_TRANSPORT"):
            build_mcp_connections({"PM2_MCP_TRANSPORT": "websocket"})
    def test_pm2_http_configuration_uses_fallback_url_and_bearer_token(self):
        connections = build_mcp_connections(
            {
                "PM2_MCP_READ_TOKEN": "read-secret",
            }
        )

        pm2 = connections[Agents.LOG_INVESTIGATOR]["pm2"]

        self.assertEqual(pm2["transport"], "streamable_http")
        self.assertEqual(pm2["url"], "http://host.docker.internal:8486/mcp")
        self.assertEqual(pm2["headers"], {"Authorization": "Bearer read-secret"})
    def test_pm2_http_fallback_url_omits_unset_authorization(self):
        connections = build_mcp_connections(
            {
                "PM2_MCP_URL": "http://localhost:8486/mcp",
            }
        )

        pm2 = connections[Agents.LOG_INVESTIGATOR]["pm2"]

        self.assertEqual(pm2["url"], "http://localhost:8486/mcp")
        self.assertNotIn("headers", pm2)
    def test_pm2_executor_connection_does_not_fall_back_to_read_token(self):
        connections = build_mcp_connections({"PM2_MCP_READ_TOKEN": "read-only"})
        executor = connections[Agents.MITIGATION_EXECUTOR]["pm2"]
        self.assertNotIn("headers", executor)
    def test_pm2_http_configuration_rejects_tokens_with_scheme_or_whitespace(self):
        with self.assertRaisesRegex(ValueError, "raw token"):
            build_mcp_connections({"PM2_MCP_READ_TOKEN": "Bearer read-only"})
    def test_pm2_is_available_to_read_only_and_executor_clients(self):
        connections = build_mcp_connections({})

        self.assertIn("pm2", connections[Agents.LOG_INVESTIGATOR])
        self.assertIn("pm2", connections[Agents.MITIGATION_ENGINEER])
        self.assertIn("pm2", connections[Agents.MITIGATION_EXECUTOR])
        self.assertIsNot(
            connections[Agents.LOG_INVESTIGATOR]["pm2"],
            connections[Agents.MITIGATION_EXECUTOR]["pm2"],
        )

if __name__ == "__main__":
    unittest.main()
