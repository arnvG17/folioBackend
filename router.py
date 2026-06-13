"""
Query Router — Two-tier classification (heuristic + LLM fallback).
"""

import re
import logging
import json
from dataclasses import dataclass

from groq import Groq

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    """Result of query routing."""
    route: str  # "personal" | "general"
    confidence: float
    tool_hints: list[str]
    query_rewritten: str


# ── Keyword Sets ────────────────────────────────────────────────

PERSONAL_KEYWORDS = {
    # Pronouns & direct references
    "you", "your", "yours", "yourself", "arnav", "arnv", "gawandi",

    # Section keywords
    "education", "degree", "university", "college", "school", "gpa",
    "experience", "work", "job", "internship", "company", "role",
    "project", "projects", "portfolio", "built", "developed", "created",
    "skill", "skills", "tech stack", "technologies", "proficient",
    "interest", "interests", "hobby", "hobbies", "passion",
    "achievement", "achievements", "award", "awards", "certification",
    "contact", "email", "linkedin", "github profile",
    "resume", "cv", "background", "bio", "about",

    # Common personal queries
    "who are", "tell me about yourself", "introduce",
    "what do you do", "where do you", "how can i reach",
}

TOOL_KEYWORDS = {
    "spotify": ["spotify", "listening", "music", "song", "track", "playing", "playlist"],
    "youtube": ["youtube", "video", "videos", "channel", "upload", "content"],
    "github": ["github", "commit", "commits", "repo", "repos", "repository",
               "code", "contribution", "contributions", "open source", "starred"],
}


# ── Tier 1: Heuristic Router ───────────────────────────────────

def _heuristic_route(query: str) -> RouteResult | None:
    """
    Fast keyword-based routing. Returns None if ambiguous.
    """
    q = query.lower().strip()

    # Check for tool hints first
    tool_hints = []
    for tool_name, keywords in TOOL_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            tool_hints.append(tool_name)

    # If tool hints found, route to personal (tools are about the user)
    if tool_hints:
        return RouteResult(
            route="personal",
            confidence=0.9,
            tool_hints=tool_hints,
            query_rewritten=query,
        )

    # Check for personal keywords
    personal_score = 0
    for keyword in PERSONAL_KEYWORDS:
        if keyword in q:
            personal_score += 1

    # Strong personal signal
    if personal_score >= 2:
        return RouteResult(
            route="personal",
            confidence=min(0.5 + personal_score * 0.15, 0.98),
            tool_hints=[],
            query_rewritten=query,
        )

    # Single keyword match — moderate confidence
    if personal_score == 1:
        return RouteResult(
            route="personal",
            confidence=0.7,
            tool_hints=[],
            query_rewritten=query,
        )

    # Check for clearly general queries (no personal pronouns at all)
    general_indicators = [
        "what is", "how does", "explain", "define", "compare",
        "difference between", "why does", "can you help",
        "write", "generate", "create a", "give me",
    ]
    for indicator in general_indicators:
        if q.startswith(indicator) and personal_score == 0:
            return RouteResult(
                route="general",
                confidence=0.85,
                tool_hints=[],
                query_rewritten=query,
            )

    # Ambiguous — return None to trigger Tier 2
    return None


# ── Tier 2: LLM Router ─────────────────────────────────────────

ROUTER_SYSTEM_PROMPT = """You are a query classifier for Arnav Gawandi's portfolio chatbot.

Classify the user's query into one of two categories:
1. "personal" — Questions about Arnav (education, projects, skills, experience, interests, contact, etc.) or requests to use his connected tools (Spotify, YouTube, GitHub).
2. "general" — General knowledge questions, coding help, or topics unrelated to Arnav.

Also identify if any tools should be invoked:
- "spotify" — if asking about music, what he's listening to, etc.
- "youtube" — if asking about his videos or channel
- "github" — if asking about his repos, commits, or code activity

Respond ONLY with valid JSON:
{"route": "personal"|"general", "confidence": 0.0-1.0, "tool_hints": [], "query_rewritten": "improved query"}"""


def _llm_route(query: str) -> RouteResult:
    """
    LLM-based routing for ambiguous queries. Adds ~300ms latency.
    """
    settings = get_settings()

    try:
        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",  # Fast small model for routing
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.1,
            max_tokens=200,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)

        return RouteResult(
            route=data.get("route", "general"),
            confidence=float(data.get("confidence", 0.5)),
            tool_hints=data.get("tool_hints", []),
            query_rewritten=data.get("query_rewritten", query),
        )

    except Exception as e:
        logger.error(f"LLM router error: {e}")
        # Fallback: default to general
        return RouteResult(
            route="general",
            confidence=0.5,
            tool_hints=[],
            query_rewritten=query,
        )


# ── Public API ──────────────────────────────────────────────────

def route_query(query: str) -> RouteResult:
    """
    Two-tier query routing:
    1. Heuristic (0ms) — returns immediately if confident
    2. LLM fallback (~300ms) — resolves ambiguous queries
    """
    # Tier 1: Heuristic
    result = _heuristic_route(query)

    if result and result.confidence >= get_settings().router_confidence_threshold:
        logger.info(
            f"[Router] Tier 1 → {result.route} "
            f"(conf={result.confidence:.2f}, tools={result.tool_hints})"
        )
        return result

    # Tier 2: LLM fallback
    logger.info("[Router] Tier 1 ambiguous → invoking Tier 2 LLM router")
    result = _llm_route(query)
    logger.info(
        f"[Router] Tier 2 → {result.route} "
        f"(conf={result.confidence:.2f}, tools={result.tool_hints})"
    )
    return result
