import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
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
    def test_default_commands_are_portable(self):
        connections = build_mcp_connections({})

        mysql = connections[Agents.LOG_INVESTIGATOR]["mysql"]
        elasticsearch = connections[Agents.LOG_INVESTIGATOR]["elasticsearch-mcp-server"]
        pm2 = connections[Agents.LOG_INVESTIGATOR]["pm2"]
        self.assertEqual(mysql["command"], "uvx")
        self.assertEqual(mysql["args"], ["mdev-mysql-mcp-server"])
        self.assertEqual(elasticsearch["command"], "uvx")
        self.assertEqual(elasticsearch["args"], ["elasticsearch-mcp-server"])
        self.assertEqual(pm2["transport"], "streamable_http")
        self.assertEqual(pm2["url"], "http://host.docker.internal:8486/mcp")
        self.assertNotIn("headers", pm2)
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

if __name__ == "__main__":
    unittest.main()
