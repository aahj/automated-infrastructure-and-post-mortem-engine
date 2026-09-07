import asyncio
import json
import os
import sys
import unittest
from collections import Counter
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from _mcp.adapter import build_mcp_connections, create_mcp_clients
from constants import Agents

MYSQL_TEST_VARIABLES = (
    "TEST_MYSQL_MCP_COMMAND",
    "TEST_MYSQL_MCP_ARGS_JSON",
    "TEST_MYSQL_HOST",
    "TEST_MYSQL_PORT",
    "TEST_MYSQL_USER",
    "TEST_MYSQL_PASSWORD",
    "TEST_MYSQL_DATABASE",
)
ELASTICSEARCH_TEST_VARIABLES = (
    "TEST_ELASTICSEARCH_MCP_COMMAND",
    "TEST_ELASTICSEARCH_MCP_ARGS_JSON",
    "TEST_ELASTICSEARCH_HOSTS",
    "TEST_ELASTICSEARCH_USERNAME",
    "TEST_ELASTICSEARCH_PASSWORD",
    "TEST_ELASTICSEARCH_VERIFY_CERTS",
)


class ExternalMCPTests(unittest.IsolatedAsyncioTestCase):
    def require_external_tests(self, *variable_names):
        if os.getenv("RUN_EXTERNAL_MCP_TESTS") != "1":
            self.skipTest("Set RUN_EXTERNAL_MCP_TESTS=1 to run live MCP tests")
        missing = [name for name in variable_names if name not in os.environ]
        if missing:
            self.skipTest(f"Missing external MCP test variables: {', '.join(missing)}")

    def build_test_environment(self, include_elasticsearch=False):
        self.require_external_tests(*MYSQL_TEST_VARIABLES)
        environment = {
            "MYSQL_MCP_COMMAND": os.environ["TEST_MYSQL_MCP_COMMAND"],
            "MYSQL_MCP_ARGS_JSON": os.environ["TEST_MYSQL_MCP_ARGS_JSON"],
            "MYSQL_HOST": os.environ["TEST_MYSQL_HOST"],
            "MYSQL_PORT": os.environ["TEST_MYSQL_PORT"],
            "MYSQL_USER": os.environ["TEST_MYSQL_USER"],
            "MYSQL_PASSWORD": os.environ["TEST_MYSQL_PASSWORD"],
            "MYSQL_DATABASE": os.environ["TEST_MYSQL_DATABASE"],
        }
        if include_elasticsearch:
            self.require_external_tests(*ELASTICSEARCH_TEST_VARIABLES)
            environment.update(
                {
                    "ELASTICSEARCH_MCP_COMMAND": os.environ["TEST_ELASTICSEARCH_MCP_COMMAND"],
                    "ELASTICSEARCH_MCP_ARGS_JSON": os.environ["TEST_ELASTICSEARCH_MCP_ARGS_JSON"],
                    "ELASTICSEARCH_HOSTS": os.environ["TEST_ELASTICSEARCH_HOSTS"],
                    "ELASTICSEARCH_USERNAME": os.environ["TEST_ELASTICSEARCH_USERNAME"],
                    "ELASTICSEARCH_PASSWORD": os.environ["TEST_ELASTICSEARCH_PASSWORD"],
                    "ELASTICSEARCH_VERIFY_CERTS": os.environ["TEST_ELASTICSEARCH_VERIFY_CERTS"],
                }
            )
        return environment

    async def test_mysql_server_connects_and_lists_tools(self):
        environment = self.build_test_environment()
        connection = build_mcp_connections(environment)[Agents.LOG_INVESTIGATOR]["mysql"]
        client = MultiServerMCPClient({"mysql": connection})

        tools = await asyncio.wait_for(client.get_tools(server_name="mysql"), timeout=30)

        self.assertGreater(len(tools), 0)
        self.assertTrue(all(tool.name for tool in tools))

    async def test_mysql_and_elasticsearch_tool_lists_are_aggregated(self):
        environment = self.build_test_environment(include_elasticsearch=True)
        connections = build_mcp_connections(environment)
        client = create_mcp_clients(connections)[Agents.LOG_INVESTIGATOR]

        mysql_tools = await asyncio.wait_for(client.get_tools(server_name="mysql"), timeout=30)
        elasticsearch_tools = await asyncio.wait_for(
            client.get_tools(server_name="elasticsearch-mcp-server"), timeout=30
        )
        aggregated_tools = await asyncio.wait_for(client.get_tools(), timeout=60)

        expected_names = Counter(tool.name for tool in mysql_tools + elasticsearch_tools)
        aggregated_names = Counter(tool.name for tool in aggregated_tools)
        self.assertGreater(len(mysql_tools), 0)
        self.assertGreater(len(elasticsearch_tools), 0)
        self.assertEqual(aggregated_names, expected_names)

    async def test_readiness_query_executes_through_mysql_tool(self):
        self.require_external_tests(
            *MYSQL_TEST_VARIABLES,
            "TEST_MYSQL_QUERY_TOOL",
            "TEST_MYSQL_QUERY_ARGS_JSON",
        )
        environment = self.build_test_environment()
        connection = build_mcp_connections(environment)[Agents.LOG_INVESTIGATOR]["mysql"]
        client = MultiServerMCPClient({"mysql": connection})
        tools = await asyncio.wait_for(client.get_tools(server_name="mysql"), timeout=30)
        query_tool_name = os.environ["TEST_MYSQL_QUERY_TOOL"]
        query_arguments = json.loads(os.environ["TEST_MYSQL_QUERY_ARGS_JSON"])
        query = query_arguments.get("sql") or query_arguments.get("query")
        normalized_query = query.strip().rstrip(";").strip() if isinstance(query, str) else ""
        self.assertTrue(normalized_query.upper().startswith("SELECT "))
        self.assertNotIn(";", normalized_query)
        query_tool = next((tool for tool in tools if tool.name == query_tool_name), None)
        self.assertIsNotNone(query_tool, f"MCP tool not found: {query_tool_name}")

        result = await asyncio.wait_for(query_tool.ainvoke(query_arguments), timeout=30)

        self.assertIn("1", str(result))

    async def test_client_recovers_after_subprocess_startup_failure(self):
        environment = self.build_test_environment()
        valid_connection = build_mcp_connections(environment)[Agents.LOG_INVESTIGATOR]["mysql"]
        client = MultiServerMCPClient(
            {
                "mysql": {
                    "command": sys.executable,
                    "args": ["-c", "raise SystemExit(7)"],
                    "transport": "stdio",
                }
            }
        )

        with self.assertRaises(Exception):
            await asyncio.wait_for(client.get_tools(server_name="mysql"), timeout=10)

        client.connections["mysql"] = valid_connection
        tools = await asyncio.wait_for(client.get_tools(server_name="mysql"), timeout=30)
        self.assertGreater(len(tools), 0)


if __name__ == "__main__":
    unittest.main()
