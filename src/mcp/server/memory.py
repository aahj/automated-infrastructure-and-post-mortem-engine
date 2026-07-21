from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Memory Server")

# How it stores: {session_id: {key: {"value": str, "last_updated_at": str}}}
#  TODO: replace in memory store with Postgres or Redis

_store: dict[str, dict] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@mcp.tool()
def memory_set(session_id: str, key: str, value: str) -> str:
    """
    Store a value in session memory.

    Values are always strings. Use JSON for complex data:
    memory_set(session_id, 'diagnostics', json.dumps({}))

    Args:
        session_id: Scopes this data to one session.
        key: Descriptive name.
        value: String value. Use JSON for lists or dicts.
    """

    if session_id not in _store:
        _store[session_id] = {}
    _store[session_id][key] = {"value": value, "last_updated_at": _now_iso()}

    return f"Stored [{key}] for session [{session_id}]"


@mcp.tool()
def memory_get(session_id: str, key: str) -> str:
    """
    Retrieve a value from session memory.

    Returns the stored value, or the string "null" if the key doesn't exist.
    Returns "null" (not Python None) so the LLM can handle the missing case
    without type errors.
    """
    session = _store.get(session_id, {})
    val = session.get(key)
    return "null" if val is None else val["value"]


@mcp.tool()
def memory_list_keys(session_id: str) -> list[str]:
    """list all keys for a stored session. Returns list of strings or empty list if no session found"""
    return list(_store.get(session_id, {}).keys())


@mcp.tool()
def memory_delete(session_id: str, key: str) -> str:
    """Delete a key from the specific session"""
    session = _store.get(session_id, {})
    if key in session:
        del session[key]
        return f"Deleted key [{key}] from session [{session_id}]"
    return f"No key [{key}] found in session [{session_id}]"


@mcp.resource("notes://session/{session_id}")
def get_session_summary(session_id: str) -> str:
    """Full summary of everything stored for a session. URI: notes://session/{session_id}"""
    session = _store.get(session_id, {})
    if not session:
        return f"# Session Memory: {session_id}\n\nNo data stored."

    lines = [f"# Session Memory: {session_id}\n"]
    for key, val in sorted(session.items()):
        lines.append(f"## {key}")
        lines.append(f" - Value: {val["value"]}\n")

    return "\n".join(lines)


if __name__ == "__main__":
    print("[MCP MEMORY] server running")
    mcp.run()
