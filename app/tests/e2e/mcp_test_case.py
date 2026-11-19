import json
import os
import sys
import unittest
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))


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


class MCPExternalTestCase(unittest.IsolatedAsyncioTestCase):
    def require_external_tests(self, *variable_names):
        if os.getenv("RUN_EXTERNAL_MCP_TESTS") != "1":
            self.skipTest("Set RUN_EXTERNAL_MCP_TESTS=1 to run live MCP tests")
        missing = [name for name in variable_names if not os.getenv(name, "").strip()]
        if missing:
            self.skipTest(f"Missing external MCP test variables: {', '.join(missing)}")

    def build_mysql_test_environment(self):
        self.require_external_tests(*MYSQL_TEST_VARIABLES)
        return {
            "MYSQL_MCP_COMMAND": os.environ["TEST_MYSQL_MCP_COMMAND"],
            "MYSQL_MCP_ARGS_JSON": os.environ["TEST_MYSQL_MCP_ARGS_JSON"],
            "MYSQL_HOST": os.environ["TEST_MYSQL_HOST"],
            "MYSQL_PORT": os.environ["TEST_MYSQL_PORT"],
            "MYSQL_USER": os.environ["TEST_MYSQL_USER"],
            "MYSQL_PASSWORD": os.environ["TEST_MYSQL_PASSWORD"],
            "MYSQL_DATABASE": os.environ["TEST_MYSQL_DATABASE"],
        }

    def build_elasticsearch_test_environment(self):
        self.require_external_tests(*ELASTICSEARCH_TEST_VARIABLES)
        return {
            "ELASTICSEARCH_MCP_COMMAND": os.environ["TEST_ELASTICSEARCH_MCP_COMMAND"],
            "ELASTICSEARCH_MCP_ARGS_JSON": os.environ["TEST_ELASTICSEARCH_MCP_ARGS_JSON"],
            "ELASTICSEARCH_HOSTS": os.environ["TEST_ELASTICSEARCH_HOSTS"],
            "ELASTICSEARCH_USERNAME": os.environ["TEST_ELASTICSEARCH_USERNAME"],
            "ELASTICSEARCH_PASSWORD": os.environ["TEST_ELASTICSEARCH_PASSWORD"],
            "ELASTICSEARCH_VERIFY_CERTS": os.environ["TEST_ELASTICSEARCH_VERIFY_CERTS"],
        }

    def build_pm2_test_environment(self):
        self.require_external_tests()
        transport = os.getenv("TEST_PM2_MCP_TRANSPORT", "stdio")
        if transport in ("http", "streamable_http"):
            required = ("TEST_PM2_MCP_URL", "TEST_PM2_MCP_READ_TOKEN")
            self.require_external_tests(*required)
            return {
                "PM2_MCP_TRANSPORT": transport,
                "PM2_MCP_URL": os.environ["TEST_PM2_MCP_URL"],
                "PM2_MCP_READ_TOKEN": os.environ["TEST_PM2_MCP_READ_TOKEN"],
            }

        self.require_external_tests(
            "TEST_PM2_MCP_COMMAND", "TEST_PM2_MCP_ARGS_JSON", "TEST_PM2_HOME"
        )
        environment = {
            "PM2_MCP_COMMAND": os.environ["TEST_PM2_MCP_COMMAND"],
            "PM2_MCP_ARGS_JSON": os.environ["TEST_PM2_MCP_ARGS_JSON"],
            "PM2_MCP_TRANSPORT": "stdio",
            "PM2_HOME": os.environ["TEST_PM2_HOME"],
        }
        working_directory = os.getenv("TEST_PM2_MCP_CWD", "").strip()
        if working_directory:
            environment["PM2_MCP_CWD"] = working_directory
        return environment

    def extract_mcp_tool_text(self, result, tool_name):
        content = result[0] if isinstance(result, tuple) and len(result) == 2 else result
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_blocks = [
                block["text"]
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ]
            if text_blocks:
                return "\n".join(text_blocks)
        else:
            self.fail(f"MCP tool {tool_name!r} returned no readable text content: {result!r}")
        self.fail(f"MCP tool {tool_name!r} returned no text blocks: {result!r}")
