import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.log_investigator import (
    InvestigatorResult,
    _is_read_only_tool_call,
    log_investigator_node,
)


class FakeInvestigationTool:
    def __init__(self, name="get_service_logs", result=None):
        self.name = name
        self.result = result or {"errors": ["database connection timed out"]}
        self.calls = []

    async def ainvoke(self, arguments):
        self.calls.append(arguments)
        return self.result


class ScriptedToolModel:
    def __init__(self, responses=None, error=None):
        self.responses = iter(responses or [])
        self.error = error

    async def ainvoke(self, messages):
        if self.error is not None:
            raise self.error
        return next(self.responses)


class FakeSynthesizerModel:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        if self.error is not None:
            raise self.error
        return self.result


class FakeChatOllama:
    def __init__(self, tool_model, synthesizer_model):
        self.tool_model = tool_model
        self.synthesizer_model = synthesizer_model

    def bind_tools(self, tools):
        return self.tool_model

    def with_structured_output(self, schema):
        return self.synthesizer_model


def chat_ollama_factory(tool_model, synthesizer_model):
    return lambda **kwargs: FakeChatOllama(tool_model, synthesizer_model)


class LogInvestigatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = {
            "messages": [],
            "service_name": "payments",
            "severity_level": "CRITICAL",
            "incident_occurred_at": "2026-09-03T08:30:00Z",
            "error_summary": "Database requests are timing out",
            "raw_alert_payload": {"error_rate": 0.42},
        }

    async def test_missing_incident_data_returns_error_without_loading_tools(self):
        state = {**self.state, "raw_alert_payload": {}}

        get_tools = AsyncMock(return_value=[])
        with patch("agents.log_investigator.get_log_investigator_tools", new=get_tools):
            result = await log_investigator_node(state)

        self.assertEqual(result["current_status"], "investigating")
        self.assertIn("raw alert payload", result["internal_error"])
        get_tools.assert_not_awaited()

    async def test_missing_service_name_returns_error_without_loading_tools(self):
        state = {**self.state, "service_name": ""}

        get_tools = AsyncMock(return_value=[])
        with patch("agents.log_investigator.get_log_investigator_tools", new=get_tools):
            result = await log_investigator_node(state)

        self.assertEqual(result["current_status"], "investigating")
        self.assertIn("service name", result["internal_error"].lower())
        get_tools.assert_not_awaited()

    async def test_missing_tools_returns_investigation_error(self):
        with patch(
            "agents.log_investigator.get_log_investigator_tools",
            new=AsyncMock(return_value=[]),
        ):
            result = await log_investigator_node(self.state)

        self.assertEqual(
            result,
            {
                "internal_error": "NO TOOL FOUND. Hence can't investigate the logs, EXITING NOW....",
                "current_status": "investigating",
            },
        )

    def test_mutating_tool_calls_are_rejected(self):
        self.assertFalse(_is_read_only_tool_call("delete_logs", {"before": "2026-09-03"}))
        self.assertFalse(
            _is_read_only_tool_call("query_database", {"sql": "UPDATE jobs SET status='done'"})
        )
        self.assertTrue(
            _is_read_only_tool_call("query_database", {"sql": "SELECT * FROM failed_jobs"})
        )

    async def test_successful_tool_evidence_is_synthesized(self):
        tool = FakeInvestigationTool()
        tool_model = ScriptedToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_service_logs",
                            "args": {"service": "payments"},
                            "id": "logs-call",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Evidence collected"),
            ]
        )
        synthesizer_model = FakeSynthesizerModel(
            result=InvestigatorResult(
                root_cause="Database connection exhaustion",
                diagnostics={"timeouts": 17},
            )
        )

        with (
            patch(
                "agents.log_investigator.get_log_investigator_tools",
                new=AsyncMock(return_value=[tool]),
            ),
            patch(
                "agents.log_investigator.ChatOllama",
                new=chat_ollama_factory(tool_model, synthesizer_model),
            ),
        ):
            result = await log_investigator_node(self.state)

        self.assertEqual(result["current_status"], "awaiting_approval")
        self.assertIsNone(result["internal_error"])
        self.assertEqual(result["root_cause"], "Database connection exhaustion")
        self.assertEqual(result["diagnostics"], {"timeouts": 17})
        self.assertEqual(tool.calls, [{"service": "payments"}])
        tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("database connection timed out", tool_messages[0].content)

    async def test_mutating_tool_request_is_not_executed(self):
        tool = FakeInvestigationTool(name="delete_logs")
        tool_model = ScriptedToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "delete_logs",
                            "args": {"before": "2026-09-03"},
                            "id": "delete-call",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Unsafe request rejected"),
            ]
        )
        synthesizer_model = FakeSynthesizerModel(
            result=InvestigatorResult(
                root_cause="Insufficient evidence",
                diagnostics={"ambiguity": "Mutation was rejected"},
            )
        )

        with (
            patch(
                "agents.log_investigator.get_log_investigator_tools",
                new=AsyncMock(return_value=[tool]),
            ),
            patch(
                "agents.log_investigator.ChatOllama",
                new=chat_ollama_factory(tool_model, synthesizer_model),
            ),
        ):
            result = await log_investigator_node(self.state)

        self.assertEqual(tool.calls, [])
        rejection = next(
            message for message in result["messages"] if isinstance(message, ToolMessage)
        )
        self.assertIn("potential state mutation", str(rejection.content))

    async def test_investigator_model_failure_returns_generated_messages(self):
        tool_model = ScriptedToolModel(error=RuntimeError("Ollama unavailable"))
        synthesizer_model = FakeSynthesizerModel()

        with (
            patch(
                "agents.log_investigator.get_log_investigator_tools",
                new=AsyncMock(return_value=[FakeInvestigationTool()]),
            ),
            patch(
                "agents.log_investigator.ChatOllama",
                new=chat_ollama_factory(tool_model, synthesizer_model),
            ),
        ):
            result = await log_investigator_node(self.state)

        self.assertEqual(result["current_status"], "investigating")
        self.assertEqual(result["internal_error"], "Log investigator failed: Ollama unavailable")
        self.assertEqual(len(result["messages"]), 2)

    async def test_synthesis_failure_returns_investigation_error(self):
        tool_model = ScriptedToolModel(responses=[AIMessage(content="Evidence collected")])
        synthesizer_model = FakeSynthesizerModel(error=RuntimeError("invalid evidence"))

        with (
            patch(
                "agents.log_investigator.get_log_investigator_tools",
                new=AsyncMock(return_value=[FakeInvestigationTool()]),
            ),
            patch(
                "agents.log_investigator.ChatOllama",
                new=chat_ollama_factory(tool_model, synthesizer_model),
            ),
        ):
            result = await log_investigator_node(self.state)

        self.assertEqual(result["current_status"], "investigating")
        self.assertEqual(
            result["internal_error"], "Could not synthesize evidence: invalid evidence"
        )
        self.assertEqual(len(result["messages"]), 3)


if __name__ == "__main__":
    unittest.main()
