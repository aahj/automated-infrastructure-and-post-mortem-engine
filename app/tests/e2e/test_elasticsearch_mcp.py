import asyncio
from collections import Counter

from tests.e2e.mcp_test_case import MCPExternalTestCase
from _mcp.adapter import build_mcp_connections, create_mcp_clients
from constants import Agents


class ElasticsearchMCPExternalTests(MCPExternalTestCase):
    async def test_elasticsearch_tools_are_available_with_mysql_aggregation(self):
        environment = self.build_mysql_test_environment()
        environment.update(self.build_elasticsearch_test_environment())
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
