import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from _mcp.adapter import build_mcp_connections, create_mcp_clients, get_tools
from constants import Agents


class ElasticsearchMCPConfigurationTests(unittest.TestCase):
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
    def test_malformed_argument_override_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "ELASTICSEARCH_MCP_ARGS_JSON"):
            build_mcp_connections({"ELASTICSEARCH_MCP_ARGS_JSON": "not-json"})

if __name__ == "__main__":
    unittest.main()
