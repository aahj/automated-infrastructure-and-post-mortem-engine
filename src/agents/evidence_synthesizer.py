import json
import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

SUMMARY_PROMPT = """
You are the Evidence Synthesizer.


OUTPUT FORMAT REQUIREMENTS
You must structure your analysis cleanly into the target JSON. The JSON must match this exact schema:
{
    "root_cause": "A concise, probabilistic statement (e.g., '85% probability: DB connection pool exhaustion caused by unindexed orders query')",
    "current_status": "investigating",
    "diagnostics" : "Key traces, metric anomalies, and failing queries found (e.g., {"app_logs":[...], "db_logs":[...]}). The type must be dict format"
}

Rules:
- current_status must always be set to "investigating"
- Never invent evidence.
"""


def parsing_llm_response_json(json_string: str) -> dict:
    """Parse LLM JSON output"""
    try:
        data = json.loads(json_string)
    except json.JSONDecodeError as e:
        raise ValueError(
            "LLM return invalid JSON.\n"
            f"Error: {e}\n"
            f"Printing first [300] char: {json_string[:300]}"
        )

    required_fields = ("root_cause", "diagnostics")
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing field in the LLM output: '{field}'")

    return data


def build_llm() -> ChatOllama:

    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=MODEL_NAME,
        temperature=0,  # 0 for deterministic structured JSON
    )


async def evidence_synthesizer_node(state: dict) -> dict:
    """
    LangGraph Node: Evidence Synthesizer

    Reads: state["messages"]
    Writes: state["root_cause"], state["current_status"], state["diagnostics"], state["internal_error"]
    """
    print("[EVIDENCE SYNTHESIZER] " "Synthesizing the evidence....")
    llm = build_llm()
    messages = [SystemMessage(content=SUMMARY_PROMPT), HumanMessage(content=state["messages"])]
    print("[EVIDENCE SYNTHESIZER] " f"Calling Model: {MODEL_NAME}")

    result = await llm.ainvoke(messages)
    try:
        parsed_data = parsing_llm_response_json(result.content)
    except ValueError as e:
        print("[EVIDENCE SYNTHESIZER] " f"Parse error: {str(e)}")
        return {"internal_error": str(e), "messages": messages + [result]}

    print("[EVIDENCE SYNTHESIZER] " f"LLM have synthesized the evidence: {str(parsed_data)}")

    return {"messages": messages + [result], "internal_error": None, **parsed_data}
