import asyncio
import json

from langchain_mcp_adapters.client import MultiServerMCPClient

from tests.e2e.mcp_test_case import MCPExternalTestCase
from _mcp.adapter import build_mcp_connections
from constants import Agents


class PM2MCPExternalTests(MCPExternalTestCase):
    async def test_server_connects_and_lists_tools(self):
        environment = self.build_pm2_test_environment()
        connection = build_mcp_connections(environment)[Agents.LOG_INVESTIGATOR]["pm2"]
        client = MultiServerMCPClient({"pm2": connection})

        tools = await asyncio.wait_for(client.get_tools(server_name="pm2"), timeout=30)

        self.assertGreater(len(tools), 0)
        tool_names = [tool.name for tool in tools]
        print(f"Tools available from PM2 MCP server: {json.dumps(tool_names, default=str)}")
        self.assertIn("list_services", tool_names)
        self.assertIn("get_status", tool_names)

    async def test_http_server_accepts_a_new_session_after_close(self):
        environment = self.build_pm2_test_environment()
        if environment.get("PM2_MCP_TRANSPORT") not in ("http", "streamable_http"):
            self.skipTest("Set TEST_PM2_MCP_TRANSPORT=streamable_http to check HTTP reconnection")
        connection = build_mcp_connections(environment)[Agents.LOG_INVESTIGATOR]["pm2"]
        client = MultiServerMCPClient({"pm2": connection})

        first_tools = await asyncio.wait_for(client.get_tools(server_name="pm2"), timeout=30)
        second_tools = await asyncio.wait_for(client.get_tools(server_name="pm2"), timeout=30)

        self.assertIn("list_services", [tool.name for tool in first_tools])
        self.assertIn("list_services", [tool.name for tool in second_tools])

    async def test_list_services_tool_returns_a_result(self):
        environment = self.build_pm2_test_environment()
        connection = build_mcp_connections(environment)[Agents.LOG_INVESTIGATOR]["pm2"]
        client = MultiServerMCPClient({"pm2": connection})

        tools = await asyncio.wait_for(client.get_tools(server_name="pm2"), timeout=30)
        process_list_tool = next((tool for tool in tools if tool.name == "list_services"), None)
        self.assertIsNotNone(process_list_tool, "MCP tool not found: list_services")

        result = await asyncio.wait_for(process_list_tool.ainvoke({}), timeout=30)
        services = json.loads(self.extract_mcp_tool_text(result, "list_services"))

        self.assertIsInstance(services, list)
        self.assertTrue(all(isinstance(service, dict) for service in services))

    async def test_get_status_returns_a_result_for_a_listed_service(self):
        environment = self.build_pm2_test_environment()
        connection = build_mcp_connections(environment)[Agents.LOG_INVESTIGATOR]["pm2"]
        client = MultiServerMCPClient({"pm2": connection})
        tools = await asyncio.wait_for(client.get_tools(server_name="pm2"), timeout=30)
        by_name = {tool.name: tool for tool in tools}
        listing = await asyncio.wait_for(by_name["list_services"].ainvoke({}), timeout=30)
        services = json.loads(self.extract_mcp_tool_text(listing, "list_services"))
        if not services:
            self.skipTest("The PM2 MCP server has no service to inspect")

        result = await asyncio.wait_for(
            by_name["get_status"].ainvoke({"name": services[0]["name"]}), timeout=30
        )
        status = json.loads(self.extract_mcp_tool_text(result, "get_status"))
        self.assertEqual(status["name"], services[0]["name"])
