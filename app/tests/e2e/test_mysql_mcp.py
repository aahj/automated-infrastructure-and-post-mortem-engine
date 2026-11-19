import asyncio
import json
import os
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient

from tests.e2e.mcp_test_case import MCPExternalTestCase
from _mcp.adapter import build_mcp_connections
from constants import Agents


class MySQLMCPExternalTests(MCPExternalTestCase):
    async def test_server_connects_and_lists_tools(self):
        environment = self.build_mysql_test_environment()
        connection = build_mcp_connections(environment)[Agents.LOG_INVESTIGATOR]["mysql"]
        client = MultiServerMCPClient({"mysql": connection})

        tools = await asyncio.wait_for(client.get_tools(server_name="mysql"), timeout=30)

        self.assertGreater(len(tools), 0)
        tool_names = [tool.name for tool in tools]
        print(f"Tools available from MySQL MCP server: {json.dumps(tool_names, default=str)}")
        self.assertTrue(all(tool_names))

    async def test_readiness_query_executes_through_mysql_tool(self):
        self.require_external_tests(
            "TEST_MYSQL_MCP_COMMAND",
            "TEST_MYSQL_MCP_ARGS_JSON",
            "TEST_MYSQL_HOST",
            "TEST_MYSQL_PORT",
            "TEST_MYSQL_USER",
            "TEST_MYSQL_PASSWORD",
            "TEST_MYSQL_DATABASE",
            "TEST_MYSQL_QUERY_TOOL",
            "TEST_MYSQL_QUERY_ARGS_JSON",
        )
        environment = self.build_mysql_test_environment()
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
        environment = self.build_mysql_test_environment()
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
