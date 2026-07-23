import os
from contextlib import nullcontext

langfuse_client = None

def _check_langfuse_configured()-> bool:
    """
    Check if Langfuse credentials are present in the environment
    Return False either any of them is missing or empty,
    System runs without observability
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY","").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY","").strip()
    return bool(public_key and secret_key)

def get_langfuse_run(session_id: str, user_id="local",    extra_config: dict | None = None,
):
    """
    Create a Langfuse callback handler for a session or None if not configured

    The handler is a Langchain CallbackHandler that langfuse provides.
    When attached to graph.invoke() in intercepts every call, LLM tool, tool call, chain invocation
    automatically. No agent code changes required.
    """
    config = {
        "configurable": {"thread_id": session_id}
    }
    if extra_config:
        config.update(extra_config)

    if not _check_langfuse_configured():
        return config, nullcontext()
    
    try:
        from langfuse import get_client, propagate_attributes
        from langfuse.langchain import CallbackHandler

        global langfuse_client

        # Initialize Langfuse client
        langfuse_client = get_client()

        config["callback"] = [CallbackHandler()]

        ctx=  propagate_attributes(
            trace_name="automated-infrastructure-incident-post-mortem-engine",
            session_id=session_id,
            user_id=user_id,
            tags=["local-inference"],
            metadata={
                "model":     os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
                "framework": "langgraph",
            },
        )
        return config, ctx

    
    except ImportError:
        print("[OBSERVABILITY] IMPORT ERROR. RUN 'pip install langfuse'")
        return config, nullcontext()
    except Exception as e:
        print(f"[OBSERVABILITY] FAILED TO CREATE HANDLER: {str(e)}")
        return config, nullcontext()

def flush_langfuse() -> None:
    """
    Flush pending traces before process exit.

    Langfuse sends traces in a background thread. Without this call,
    the last few seconds of traces may be lost when the process exits.
    """
    if not _check_langfuse_configured():
        return
    try:
        langfuse_client().flush()
    except Exception:
        pass  # Best-effort. Don't crash on exit.