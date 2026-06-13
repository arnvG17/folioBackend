"""
Personal Pipeline — RAG-powered response using me.txt knowledge.
"""

import logging
from collections.abc import AsyncGenerator

from groq import Groq

from config import get_settings
from knowledge_base import get_knowledge_base

logger = logging.getLogger(__name__)


PERSONAL_SYSTEM_PROMPT = """You are Arnav Gawandi, responding on your portfolio website's chatbot.

RULES:
1. Answer using ONLY the provided context from your personal knowledge base.
2. Speak in first person ("I", "my", "me") as Arnav.
3. For factual queries, give concise answers (2-4 sentences).
4. If the context doesn't contain enough information, say "I haven't shared that detail on my portfolio yet, but feel free to reach out to me directly!"
5. NEVER hallucinate or make up information not in the context.
6. Be warm, professional, and personable.
7. If tool data (Spotify, GitHub, YouTube) is provided, naturally incorporate it into your response.

CONTEXT:
{context}

{tool_context}"""


def _build_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a context string."""
    if not chunks:
        return "No relevant context found."

    parts = []
    for i, chunk in enumerate(chunks):
        section = chunk.get("section", "UNKNOWN")
        text = chunk.get("text", "")
        score = chunk.get("score", 0)
        parts.append(f"[{section}] (relevance: {score:.2f})\n{text}")

    return "\n\n---\n\n".join(parts)


async def stream_personal_response(
    query: str,
    tool_context: str = "",
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """
    RAG pipeline: retrieve → prompt → stream via Groq.

    Yields tokens one at a time for SSE streaming.
    """
    settings = get_settings()
    kb = get_knowledge_base()

    # 1. Retrieve relevant chunks
    chunks = kb.search(query, top_k=settings.rag_top_k)
    context_str = _build_context(chunks)

    logger.info(
        f"[Personal] Retrieved {len(chunks)} chunks for query: {query[:60]}..."
    )

    # 2. Build messages
    system_prompt = PERSONAL_SYSTEM_PROMPT.format(
        context=context_str,
        tool_context=f"TOOL DATA:\n{tool_context}" if tool_context else "",
    )

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history if provided
    if history:
        # Keep last 6 messages max to stay within context window
        for msg in history[-6:]:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

    messages.append({"role": "user", "content": query})

    # 3. Stream from Groq
    client = Groq(api_key=settings.groq_api_key)

    try:
        stream = client.chat.completions.create(
            model=settings.groq_model,
            messages=messages,
            temperature=settings.groq_temperature,
            max_tokens=settings.groq_max_tokens,
            stream=True,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    except Exception as e:
        logger.error(f"[Personal] Groq streaming error: {e}")
        yield f"Sorry, I'm having trouble generating a response right now. Please try again."
