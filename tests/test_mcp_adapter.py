import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, call, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from _mcp.adapter import build_mcp_connections, create_mcp_clients, get_tools
from constants import Agents


class MCPAdapterConfigurationTests(unittest.TestCase):
    def test_environment_overrides_commands_arguments_and_credentials(self):
        environment = {
            "MYSQL_MCP_COMMAND": "custom-mysql-mcp",
            "MYSQL_MCP_ARGS_JSON": '["--stdio", "--readonly"]',
            "MYSQL_HOST": "mysql.test",
            "MYSQL_PORT": "3307",
            "MYSQL_USER": "integration-user",
            "MYSQL_PASSWORD": "secret",
            "MYSQL_DATABASE": "incident_test",
            "ELASTICSEARCH_MCP_COMMAND": "custom-elasticsearch-mcp",
            "ELASTICSEARCH_MCP_ARGS_JSON": '["--transport", "stdio"]',
            "ELASTICSEARCH_HOSTS": "https://elasticsearch.test:9200",
            "ELASTICSEARCH_USERNAME": "elastic-user",
            "ELASTICSEARCH_PASSWORD": "elastic-secret",
            "ELASTICSEARCH_VERIFY_CERTS": "true",
        }

        connections = build_mcp_connections(environment)

        investigator_mysql = connections[Agents.LOG_INVESTIGATOR]["mysql"]
        investigator_elasticsearch = connections[Agents.LOG_INVESTIGATOR][
            "elasticsearch-mcp-server"
        ]
        self.assertEqual(investigator_mysql["command"], "custom-mysql-mcp")
        self.assertEqual(investigator_mysql["args"], ["--stdio", "--readonly"])
        self.assertEqual(investigator_mysql["env"]["MYSQL_HOST"], "mysql.test")
        self.assertEqual(investigator_mysql["env"]["MYSQL_PORT"], "3307")
        self.assertEqual(investigator_mysql["env"]["MYSQL_USER"], "integration-user")
        self.assertEqual(investigator_mysql["env"]["MYSQL_PASSWORD"], "secret")
        self.assertEqual(investigator_mysql["env"]["MYSQL_DATABASE"], "incident_test")
        self.assertEqual(investigator_elasticsearch["command"], "custom-elasticsearch-mcp")
        self.assertEqual(investigator_elasticsearch["args"], ["--transport", "stdio"])
        self.assertEqual(
            investigator_elasticsearch["env"]["ELASTICSEARCH_HOSTS"],
            "https://elasticsearch.test:9200",
        )
        self.assertEqual(investigator_elasticsearch["env"]["ELASTICSEARCH_VERIFY_CERTS"], "true")

    def test_connections_apply_agent_specific_safety_settings(self):
        connections = build_mcp_connections({})

        investigator = connections[Agents.LOG_INVESTIGATOR]
        engineer = connections[Agents.MITIGATION_ENGINEER]
        executor = connections[Agents.MITIGATION_EXECUTOR]
        self.assertIs(investigator, engineer)
        self.assertEqual(
            investigator["elasticsearch-mcp-server"]["env"]["DISABLE_HIGH_RISK_OPERATIONS"],
            "true",
        )
        self.assertEqual(
            executor["elasticsearch-mcp-server"]["env"]["DISABLE_HIGH_RISK_OPERATIONS"],
            "false",
        )

    def test_default_commands_are_portable(self):
        connections = build_mcp_connections({})

        mysql = connections[Agents.LOG_INVESTIGATOR]["mysql"]
        elasticsearch = connections[Agents.LOG_INVESTIGATOR]["elasticsearch-mcp-server"]
        pm2 = connections[Agents.LOG_INVESTIGATOR]["pm2"]
        self.assertEqual(mysql["command"], "uvx")
        self.assertEqual(mysql["args"], ["mdev-mysql-mcp-server"])
        self.assertEqual(elasticsearch["command"], "uvx")
        self.assertEqual(elasticsearch["args"], ["elasticsearch-mcp-server"])
        self.assertEqual(pm2["command"], "pm2-mcp")
        self.assertEqual(pm2["args"], [])
        self.assertEqual(pm2["transport"], "stdio")

    def test_pm2_configuration_overrides_command_arguments_and_runtime_environment(self):
        environment = {
            "PM2_MCP_COMMAND": "npx",
            "PM2_MCP_ARGS_JSON": '["-y", "github:promptexecution/pm2-mcp", "pm2-mcp"]',
            "PM2_HOME": "C:/pm2",
            "PM2_MCP_NO_DAEMON": "false",
            "PM2_SILENT": "false",
        }

        connections = build_mcp_connections(environment)

        pm2 = connections[Agents.LOG_INVESTIGATOR]["pm2"]
        self.assertEqual(pm2["command"], "npx")
        self.assertEqual(
            pm2["args"], ["-y", "github:promptexecution/pm2-mcp", "pm2-mcp"]
        )
        self.assertEqual(
            pm2["env"],
            {"PM2_HOME": "C:/pm2", "PM2_MCP_NO_DAEMON": "false", "PM2_SILENT": "false"},
        )

    def test_pm2_is_available_to_read_only_and_executor_clients(self):
        connections = build_mcp_connections({})

        self.assertIn("pm2", connections[Agents.LOG_INVESTIGATOR])
        self.assertIn("pm2", connections[Agents.MITIGATION_ENGINEER])
        self.assertIn("pm2", connections[Agents.MITIGATION_EXECUTOR])
        self.assertIs(
            connections[Agents.LOG_INVESTIGATOR]["pm2"],
            connections[Agents.MITIGATION_EXECUTOR]["pm2"],
        )

    def test_invalid_argument_override_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "MYSQL_MCP_ARGS_JSON"):
            build_mcp_connections({"MYSQL_MCP_ARGS_JSON": '{"not": "a list"}'})

    def test_malformed_argument_override_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "ELASTICSEARCH_MCP_ARGS_JSON"):
            build_mcp_connections({"ELASTICSEARCH_MCP_ARGS_JSON": "not-json"})

    def test_unset_credentials_are_not_forwarded_to_subprocesses(self):
        connections = build_mcp_connections({})

        mysql_environment = connections[Agents.LOG_INVESTIGATOR]["mysql"]["env"]
        elasticsearch_environment = connections[Agents.LOG_INVESTIGATOR][
            "elasticsearch-mcp-server"
        ]["env"]
        self.assertNotIn("MYSQL_PASSWORD", mysql_environment)
        self.assertNotIn("MYSQL_DATABASE", mysql_environment)
        self.assertNotIn("ELASTICSEARCH_USERNAME", elasticsearch_environment)
        self.assertNotIn("ELASTICSEARCH_PASSWORD", elasticsearch_environment)

    def test_client_creation_passes_connections_without_spawning_processes(self):
        connections = build_mcp_connections({})
        read_only_client = object()
        executor_client = object()

        with patch("_mcp.adapter.MultiServerMCPClient") as client_class:
            client_class.side_effect = [read_only_client, executor_client]
            clients = create_mcp_clients(connections)

        self.assertEqual(client_class.call_count, 2)
        self.assertEqual(
            client_class.call_args_list,
            [
                call(connections[Agents.LOG_INVESTIGATOR]),
                call(connections[Agents.MITIGATION_EXECUTOR]),
            ],
        )
        self.assertIs(clients[Agents.LOG_INVESTIGATOR], read_only_client)
        self.assertIs(clients[Agents.MITIGATION_ENGINEER], read_only_client)
        self.assertIs(clients[Agents.MITIGATION_EXECUTOR], executor_client)


class MCPAdapterRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_omitted_server_name_requests_aggregated_tools(self):
        client = AsyncMock()
        expected_tools = [object()]
        client.get_tools.return_value = expected_tools

        with patch.dict(
            "_mcp.adapter.mcp_clients",
            {Agents.LOG_INVESTIGATOR: client},
            clear=True,
        ):
            tools = await get_tools(Agents.LOG_INVESTIGATOR)

        self.assertIs(tools, expected_tools)
        client.get_tools.assert_awaited_once_with(server_name=None)

    async def test_agents_route_to_their_expected_clients(self):
        read_only_client = AsyncMock()
        executor_client = AsyncMock()
        expected_tools = [object()]
        read_only_client.get_tools.return_value = expected_tools
        executor_client.get_tools.return_value = expected_tools

        with patch.dict(
            "_mcp.adapter.mcp_clients",
            {
                Agents.LOG_INVESTIGATOR: read_only_client,
                Agents.MITIGATION_ENGINEER: read_only_client,
                Agents.MITIGATION_EXECUTOR: executor_client,
            },
            clear=True,
        ):
            investigator_tools = await get_tools(Agents.LOG_INVESTIGATOR, server_name="mysql")
            engineer_tools = await get_tools(
                Agents.MITIGATION_ENGINEER, server_name="elasticsearch-mcp-server"
            )
            executor_tools = await get_tools(Agents.MITIGATION_EXECUTOR, server_name="mysql")

        self.assertIs(investigator_tools, expected_tools)
        self.assertIs(engineer_tools, expected_tools)
        self.assertIs(executor_tools, expected_tools)
        self.assertEqual(
            read_only_client.get_tools.await_args_list,
            [
                call(server_name="mysql"),
                call(server_name="elasticsearch-mcp-server"),
            ],
        )
        executor_client.get_tools.assert_awaited_once_with(server_name="mysql")

    async def test_handshake_failure_is_not_hidden(self):
        client = AsyncMock()
        client.get_tools.side_effect = ConnectionError("MCP handshake failed")

        with patch.dict(
            "_mcp.adapter.mcp_clients",
            {Agents.LOG_INVESTIGATOR: client},
            clear=True,
        ):
            with self.assertRaisesRegex(ConnectionError, "MCP handshake failed"):
                await get_tools(Agents.LOG_INVESTIGATOR, server_name="mysql")

    async def test_unknown_agent_returns_none(self):
        self.assertIsNone(await get_tools(object()))


if __name__ == "__main__":
    unittest.main()
