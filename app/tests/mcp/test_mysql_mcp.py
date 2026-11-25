import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from _mcp.adapter import build_mcp_connections, create_mcp_clients, get_tools
from constants import Agents


class MySQLMCPConfigurationTests(unittest.TestCase):
    def test_invalid_argument_override_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "MYSQL_MCP_ARGS_JSON"):
            build_mcp_connections({"MYSQL_MCP_ARGS_JSON": '{"not": "a list"}'})

if __name__ == "__main__":
    unittest.main()
