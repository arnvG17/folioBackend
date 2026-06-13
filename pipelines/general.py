"""
General Pipeline — Direct LLM response without RAG retrieval.
"""

import logging
from collections.abc import AsyncGenerator

from groq import Groq

from config import get_settings

logger = logging.getLogger(__name__)


GENERAL_SYSTEM_PROMPT = """You are a helpful AI assistant on Arnav Gawandi's portfolio website.

RULES:
1. Be concise and helpful.
2. For coding questions, provide clear explanations and code examples.
3. For general knowledge, give accurate and informative responses.
4. Keep responses focused — aim for 2-5 sentences unless more detail is needed.
5. If asked about Arnav specifically, redirect: "For questions about Arnav, just ask me something like 'Tell me about your projects' and I'll pull from his knowledge base!"
6. Be warm and professional.

{tool_context}"""


async def stream_general_response(
    query: str,
    tool_context: str = "",
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Direct LLM pipeline — no retrieval, fast response (<2s).

    Yields tokens one at a time for SSE streaming.
    """
    settings = get_settings()

    system_prompt = GENERAL_SYSTEM_PROMPT.format(
        tool_context=f"TOOL DATA:\n{tool_context}" if tool_context else "",
    )

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history
    if history:
        for msg in history[-6:]:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

    messages.append({"role": "user", "content": query})

    # Stream from Groq
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
        logger.error(f"[General] Groq streaming error: {e}")
        yield "Sorry, I'm having trouble right now. Please try again."
