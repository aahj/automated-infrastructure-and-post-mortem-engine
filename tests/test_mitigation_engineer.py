import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.mitigation_engineer import (
    VerificationResult,
    is_read_only_tool_call,
    mitigation_engineer_node,
)


class FakeHealthTool:
    name = "get_service_health"

    async def ainvoke(self, arguments):
        return {"status": 200, "latency_ms": 12, "error_rate": 0}


class FakeToolModel:
    def __init__(self):
        self.responses = iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_service_health",
                            "args": {},
                            "id": "health-call",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Health evidence collected"),
            ]
        )

    async def ainvoke(self, messages):
        return next(self.responses)


class FakeDecisionModel:
    async def ainvoke(self, messages):
        return VerificationResult(
            is_resolved=True,
            summary="Health endpoint is stable",
            checks_performed=["HTTP health check"],
            evidence={"status": 200, "latency_ms": 12},
        )


class FakeChatOllama:
    def __init__(self, **kwargs):
        pass

    def bind_tools(self, tools):
        return FakeToolModel()

    def with_structured_output(self, schema):
        return FakeDecisionModel()


class MitigationEngineerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = {
            "messages": [],
            "incident_id": "incident-1",
            "service_name": "payments",
            "root_cause": "database lock contention",
            "diagnostics": {"blocked_threads": 4},
        }

    async def test_missing_tools_cannot_mark_incident_resolved(self):
        with patch(
            "agents.mitigation_engineer.get_mitigation_engineer_tools",
            new=AsyncMock(return_value=[]),
        ):
            result = await mitigation_engineer_node(self.state)

        self.assertFalse(result["is_resolved"])
        self.assertEqual(result["current_status"], "failed_mitigation")

    async def test_successful_probe_drives_structured_resolution(self):
        with (
            patch(
                "agents.mitigation_engineer.get_mitigation_engineer_tools",
                new=AsyncMock(return_value=[FakeHealthTool()]),
            ),
            patch("agents.mitigation_engineer.ChatOllama", FakeChatOllama),
        ):
            result = await mitigation_engineer_node(self.state)

        self.assertTrue(result["is_resolved"])
        self.assertEqual(result["current_status"], "resolved")
        self.assertEqual(result["verification_result"]["checks_performed"], ["HTTP health check"])

    def test_mutating_verification_calls_are_rejected(self):
        self.assertFalse(is_read_only_tool_call("kill_blocking_query", {"id": 42}))
        self.assertFalse(is_read_only_tool_call("query_database", {"sql": "DELETE FROM incidents"}))
        self.assertTrue(is_read_only_tool_call("query_database", {"sql": "SHOW PROCESSLIST"}))


if __name__ == "__main__":
    unittest.main()
