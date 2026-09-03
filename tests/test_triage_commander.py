import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.triage_commander import parsing_llm_response_json, triage_node


class FakeTriageModel:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        if self.error is not None:
            raise self.error
        return self.response


class TriageCommanderParsingTests(unittest.TestCase):
    def test_valid_json_is_parsed(self):
        payload = (
            '{"service_name": "payments", "severity_level": "CRITICAL", '
            '"error_summary": "Database unavailable"}'
        )

        self.assertEqual(
            parsing_llm_response_json(payload),
            {
                "service_name": "payments",
                "severity_level": "CRITICAL",
                "error_summary": "Database unavailable",
            },
        )

    def test_malformed_json_raises_descriptive_value_error(self):
        with self.assertRaisesRegex(ValueError, "LLM return invalid JSON"):
            parsing_llm_response_json('{"service_name":')

    def test_missing_required_field_raises_value_error(self):
        payload = '{"service_name": "payments", "severity_level": "CRITICAL"}'

        with self.assertRaisesRegex(ValueError, "Missing field.*'error_summary'"):
            parsing_llm_response_json(payload)


class TriageCommanderNodeTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "raw_alert_payload": {"alert": "Payments database is unavailable"},
            "incident_occurred_at": "2026-09-03T08:30:00Z",
        }

    def test_empty_payload_returns_internal_error_without_building_model(self):
        state = {**self.state, "raw_alert_payload": {}}

        with patch("agents.triage_commander.build_triage_llm") as build_model:
            result = triage_node(state)

        self.assertEqual(result, {"internal_error": "No raw alert payload provided"})
        build_model.assert_not_called()

    def test_successful_triage_returns_structured_alert_and_messages(self):
        response = AIMessage(
            content=(
                '{"service_name": "payments", "severity_level": "CRITICAL", '
                '"incident_occurred_at": "2026-09-03T08:25:00Z", '
                '"error_summary": "Database unavailable", "current_status": "triaged"}'
            )
        )
        model = FakeTriageModel(response=response)

        with patch("agents.triage_commander.build_triage_llm", return_value=model):
            result = triage_node(self.state)

        self.assertEqual(result["service_name"], "payments")
        self.assertEqual(result["severity_level"], "CRITICAL")
        self.assertEqual(result["incident_occurred_at"], "2026-09-03T08:25:00Z")
        self.assertEqual(result["error_summary"], "Database unavailable")
        self.assertIsNone(result["internal_error"])
        self.assertEqual(result["messages"][-1], response)
        self.assertIsInstance(model.messages[0], SystemMessage)
        self.assertIsInstance(model.messages[1], HumanMessage)
        self.assertEqual(model.messages[1].content, str(self.state["raw_alert_payload"]))

    def test_missing_incident_timestamp_uses_timestamp_from_state(self):
        response = AIMessage(
            content=(
                '{"service_name": "payments", "severity_level": "WARNING", '
                '"error_summary": "Elevated database latency"}'
            )
        )

        with patch(
            "agents.triage_commander.build_triage_llm",
            return_value=FakeTriageModel(response=response),
        ):
            result = triage_node(self.state)

        self.assertEqual(result["incident_occurred_at"], "2026-09-03T08:30:00Z")

    def test_model_error_is_returned_as_internal_error(self):
        model = FakeTriageModel(error=RuntimeError("Ollama unavailable"))

        with patch("agents.triage_commander.build_triage_llm", return_value=model):
            result = triage_node(self.state)

        self.assertEqual(result["internal_error"], "Ollama unavailable")
        self.assertEqual(result["messages"], model.messages)

    def test_invalid_model_output_is_returned_as_internal_error(self):
        response = AIMessage(content="not valid JSON")

        with patch(
            "agents.triage_commander.build_triage_llm",
            return_value=FakeTriageModel(response=response),
        ):
            result = triage_node(self.state)

        self.assertIn("LLM return invalid JSON", result["internal_error"])
        self.assertEqual(result["messages"][-1], response)


if __name__ == "__main__":
    unittest.main()
