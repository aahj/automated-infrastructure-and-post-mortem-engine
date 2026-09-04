import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.mitigation_executor import MAX_TOOL_ROUNDS, mitigation_executor_node


class FakeExecutionTool:
    def __init__(self, name="restart_service", result=None, error=None):
        self.name = name
        self.result = result or {"status": "restarted", "service": "payments"}
        self.error = error
        self.calls = []

    async def ainvoke(self, arguments):
        self.calls.append(arguments)
        if self.error is not None:
            raise self.error
        return self.result


class ScriptedExecutorModel:
    def __init__(self, responses=None, error=None):
        self.responses = iter(responses or [])
        self.error = error
        self.call_count = 0

    async def ainvoke(self, messages):
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return next(self.responses)


class FakeChatOllama:
    def __init__(self, model):
        self.model = model

    def bind_tools(self, tools):
        return self.model


def chat_ollama_factory(model):
    return lambda **kwargs: FakeChatOllama(model)


def tool_call_response(name="restart_service", call_id="restart-call"):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": {"service": "payments"},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


class MitigationExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = {
            "messages": [],
            "incident_id": "incident-1",
            "service_name": "payments",
            "severity_level": "CRITICAL",
            "incident_occurred_at": "2026-09-04T08:30:00Z",
            "error_summary": "Payment requests are failing",
            "raw_alert_payload": {"error_rate": 0.42},
            "root_cause": "Stale service connections",
            "diagnostics": {"connection_errors": 21},
        }

    async def test_missing_required_data_returns_before_loading_tools(self):
        state = {**self.state, "root_cause": ""}
        get_tools = AsyncMock(return_value=[])

        with patch("agents.mitigation_executor.get_mitigation_executor_tools", new=get_tools):
            result = await mitigation_executor_node(state)

        self.assertIn("Missing required fields", result["internal_error"])
        get_tools.assert_not_awaited()

    async def test_missing_incident_id_returns_before_loading_tools(self):
        state = {**self.state, "incident_id": ""}
        get_tools = AsyncMock(return_value=[])

        with patch("agents.mitigation_executor.get_mitigation_executor_tools", new=get_tools):
            result = await mitigation_executor_node(state)

        self.assertIn("Missing required fields", result["internal_error"])
        get_tools.assert_not_awaited()

    async def test_missing_tools_returns_failed_mitigation(self):
        with patch(
            "agents.mitigation_executor.get_mitigation_executor_tools",
            new=AsyncMock(return_value=[]),
        ):
            result = await mitigation_executor_node(self.state)

        self.assertEqual(
            result,
            {
                "internal_error": "NO TOOL FOUND. EXITING NOW..",
                "current_status": "failed_mitigation",
            },
        )

    async def test_successful_tool_execution_returns_tool_evidence(self):
        tool = FakeExecutionTool()
        model = ScriptedExecutorModel(
            responses=[tool_call_response(), AIMessage(content="Service restarted successfully")]
        )

        with (
            patch(
                "agents.mitigation_executor.get_mitigation_executor_tools",
                new=AsyncMock(return_value=[tool]),
            ),
            patch(
                "agents.mitigation_executor.ChatOllama", new=chat_ollama_factory(model)
            ),
        ):
            result = await mitigation_executor_node(self.state)

        self.assertEqual(result["current_status"], "mitigating")
        self.assertIsNone(result["internal_error"])
        self.assertEqual(tool.calls, [{"service": "payments"}])
        tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn('"status": "restarted"', tool_messages[0].content)

    async def test_unknown_tool_request_returns_explanatory_tool_message(self):
        model = ScriptedExecutorModel(
            responses=[
                tool_call_response(name="delete_cluster", call_id="unknown-call"),
                AIMessage(content="Requested tool was unavailable"),
            ]
        )

        with (
            patch(
                "agents.mitigation_executor.get_mitigation_executor_tools",
                new=AsyncMock(return_value=[FakeExecutionTool()]),
            ),
            patch(
                "agents.mitigation_executor.ChatOllama", new=chat_ollama_factory(model)
            ),
        ):
            result = await mitigation_executor_node(self.state)

        tool_message = next(
            message for message in result["messages"] if isinstance(message, ToolMessage)
        )
        self.assertIn("No tool is available: delete_cluster", str(tool_message.content))

    async def test_tool_failure_is_captured_in_tool_message(self):
        tool = FakeExecutionTool(error=TimeoutError("service manager timed out"))
        model = ScriptedExecutorModel(
            responses=[tool_call_response(), AIMessage(content="Restart failed")]
        )

        with (
            patch(
                "agents.mitigation_executor.get_mitigation_executor_tools",
                new=AsyncMock(return_value=[tool]),
            ),
            patch(
                "agents.mitigation_executor.ChatOllama", new=chat_ollama_factory(model)
            ),
        ):
            result = await mitigation_executor_node(self.state)

        tool_message = next(
            message for message in result["messages"] if isinstance(message, ToolMessage)
        )
        self.assertEqual(
            tool_message.content,
            "Tool calling failed: TimeoutError: service manager timed out",
        )

    async def test_model_failure_returns_failed_mitigation(self):
        model = ScriptedExecutorModel(error=RuntimeError("Ollama unavailable"))

        with (
            patch(
                "agents.mitigation_executor.get_mitigation_executor_tools",
                new=AsyncMock(return_value=[FakeExecutionTool()]),
            ),
            patch(
                "agents.mitigation_executor.ChatOllama", new=chat_ollama_factory(model)
            ),
        ):
            result = await mitigation_executor_node(self.state)

        self.assertEqual(result["current_status"], "failed_mitigation")
        self.assertEqual(
            result["internal_error"], "Mitigation Executor Failed: Ollama unavailable"
        )
        # print("==>", result["messages"])
        self.assertEqual(len(result["messages"]), 2)

    async def test_execution_stops_at_configured_tool_round_limit(self):
        tool = FakeExecutionTool()
        model = ScriptedExecutorModel(
            responses=[
                tool_call_response(call_id=f"restart-call-{index}")
                for index in range(MAX_TOOL_ROUNDS)
            ]
        )

        with (
            patch(
                "agents.mitigation_executor.get_mitigation_executor_tools",
                new=AsyncMock(return_value=[tool]),
            ),
            patch(
                "agents.mitigation_executor.ChatOllama", new=chat_ollama_factory(model)
            ),
        ):
            result = await mitigation_executor_node(self.state)

        self.assertEqual(result["current_status"], "mitigating")
        self.assertEqual(len(tool.calls), MAX_TOOL_ROUNDS)
        self.assertEqual(model.call_count, MAX_TOOL_ROUNDS)


if __name__ == "__main__":
    unittest.main()
