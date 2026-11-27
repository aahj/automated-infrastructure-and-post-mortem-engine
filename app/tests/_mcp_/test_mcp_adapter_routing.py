import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from _mcp.adapter import build_mcp_connections, create_mcp_clients, get_tools
from constants import Agents


class MCPAdapterRoutingTests(unittest.IsolatedAsyncioTestCase):
    # async def test_pm2_mutating_tools_are_available_only_to_executor(self):
    #     tools = [
    #         SimpleNamespace(name="list_services"),
    #         SimpleNamespace(name="get_status"),
    #         SimpleNamespace(name="restart_service"),
    #         SimpleNamespace(name="stop_service"),
    #         SimpleNamespace(name="start_service"),
    #         SimpleNamespace(name="reload_service"),
    #         SimpleNamespace(name="save"),
    #         SimpleNamespace(name="flush_logs"),
    #     ]
    #     read_only_client = AsyncMock()
    #     executor_client = AsyncMock()
    #     read_only_client.get_tools.return_value = tools
    #     executor_client.get_tools.return_value = tools

    #     with patch.dict(
    #         "_mcp.adapter.mcp_clients",
    #         {
    #             Agents.LOG_INVESTIGATOR: read_only_client,
    #             Agents.MITIGATION_ENGINEER: read_only_client,
    #             Agents.MITIGATION_EXECUTOR: executor_client,
    #         },
    #         clear=True,
    #     ):
    #         investigator_tools = await get_tools(Agents.LOG_INVESTIGATOR)
    #         engineer_tools = await get_tools(Agents.MITIGATION_ENGINEER)
    #         executor_tools = await get_tools(Agents.MITIGATION_EXECUTOR)

    #     self.assertEqual(
    #         [tool.name for tool in investigator_tools],
    #         ["list_services", "get_status"],
    #     )
    #     self.assertEqual(
    #         [tool.name for tool in engineer_tools],
    #         ["list_services", "get_status"],
    #     )
    #     self.assertEqual([tool.name for tool in executor_tools], [tool.name for tool in tools])

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
