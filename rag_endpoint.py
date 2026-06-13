"""
/rag Endpoint — Single entry point with SSE streaming.
"""

import json
import time
import logging
import re
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from router import route_query
from pipelines.personal import stream_personal_response
from pipelines.general import stream_general_response
from tools.agent import execute_tools

logger = logging.getLogger(__name__)

rag_router = APIRouter()


# ── Request / Response Models ───────────────────────────────────

class RagRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = None
    history: list[dict] | None = None


# ── Input Sanitization ──────────────────────────────────────────

def sanitize_input(text: str) -> str:
    """Basic input sanitization."""
    # Remove potential injection patterns
    text = text.strip()
    # Remove excessive whitespace
    text = re.sub(r"\s+", " ", text)
    # Limit length
    return text[:2000]


# ── SSE Helpers ─────────────────────────────────────────────────

def sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Endpoint ────────────────────────────────────────────────────

@rag_router.post("/rag")
async def rag_endpoint(req: RagRequest, request: Request):
    """
    Smart Agent RAG endpoint with SSE streaming.

    Flow:
    1. Sanitize input
    2. Route query (heuristic → LLM fallback)
    3. Execute tools if needed (parallel)
    4. Stream response from appropriate pipeline
    """
    start_time = time.time()
    query = sanitize_input(req.query)

    logger.info(f"[/rag] Query: {query[:80]}...")

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            # 1. Route the query
            route_result = route_query(query)

            # 2. Execute tools in parallel if hinted
            tool_context = ""
            if route_result.tool_hints:
                tool_context = await execute_tools(route_result.tool_hints)

            # 3. Emit metadata event
            yield sse_event("metadata", {
                "route": route_result.route,
                "confidence": round(route_result.confidence, 2),
                "tools_used": route_result.tool_hints,
                "query_rewritten": route_result.query_rewritten,
            })

            # 4. Stream from appropriate pipeline
            token_count = 0

            if route_result.route == "personal":
                async for token in stream_personal_response(
                    query=route_result.query_rewritten,
                    tool_context=tool_context,
                    history=req.history,
                ):
                    token_count += 1
                    yield sse_event("token", {"content": token})
            else:
                async for token in stream_general_response(
                    query=route_result.query_rewritten,
                    tool_context=tool_context,
                    history=req.history,
                ):
                    token_count += 1
                    yield sse_event("token", {"content": token})

            # 5. Emit done event
            elapsed = round((time.time() - start_time) * 1000)
            yield sse_event("done", {
                "total_tokens": token_count,
                "latency_ms": elapsed,
                "route": route_result.route,
            })

            logger.info(
                f"[/rag] Done — route={route_result.route}, "
                f"tokens={token_count}, latency={elapsed}ms"
            )
        except Exception as e:
            logger.error(f"[/rag] Unhandled error during streaming: {e}", exc_info=True)
            yield sse_event("token", {"content": f"\n\n[System Error: {str(e)}]"})
            yield sse_event("done", {"total_tokens": 0, "latency_ms": 0, "route": "error"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ── Backward-Compatible /chat ───────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    k: int = 4


@rag_router.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """
    Legacy /chat endpoint — wraps /rag and returns a JSON response.
    Kept for backward compatibility.
    """
    query = sanitize_input(req.query)

    # Route
    route_result = route_query(query)

    # Execute tools
    tool_context = ""
    if route_result.tool_hints:
        tool_context = await execute_tools(route_result.tool_hints)

    # Collect full response (non-streaming)
    full_response = ""
    if route_result.route == "personal":
        async for token in stream_personal_response(
            query=route_result.query_rewritten,
            tool_context=tool_context,
        ):
            full_response += token
    else:
        async for token in stream_general_response(
            query=route_result.query_rewritten,
            tool_context=tool_context,
        ):
            full_response += token

    return {
        "answer": full_response,
        "route": route_result.route,
        "confidence": round(route_result.confidence, 2),
        "tools_used": route_result.tool_hints,
    }
