"""
Tool Agent — Orchestrates parallel tool execution and formats results.
"""

import asyncio
import logging
from typing import Any

from tools.lastfm import LastFmTool
from tools.youtube import YouTubeTool
from tools.github import GitHubTool

logger = logging.getLogger(__name__)


# ── Singleton tool instances ────────────────────────────────────

_lastfm = LastFmTool()
_youtube = YouTubeTool()
_github = GitHubTool()

TOOL_MAP = {
    "spotify": _lastfm,   # Router hints "spotify" for music; LastFmTool handles it
    "youtube": _youtube,
    "github": _github,
}


# ── Orchestrator ────────────────────────────────────────────────

async def execute_tools(tool_hints: list[str]) -> str:
    """
    Execute all hinted tools in parallel and return a formatted context string.

    Args:
        tool_hints: List of tool names to execute (e.g., ["spotify", "github"])

    Returns:
        Formatted string of tool results for injection into LLM prompt.
    """
    if not tool_hints:
        return ""

    # Filter to valid tools
    valid_hints = [h for h in tool_hints if h in TOOL_MAP]
    if not valid_hints:
        return ""

    logger.info(f"[ToolAgent] Executing tools: {valid_hints}")

    # Execute all tools in parallel
    tasks = []
    for hint in valid_hints:
        tool = TOOL_MAP[hint]
        tasks.append(tool.run())

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Format results into context string
    parts = []
    for hint, result in zip(valid_hints, results):
        if isinstance(result, Exception):
            logger.error(f"[ToolAgent] {hint} failed: {result}")
            continue

        if isinstance(result, dict) and "error" in result:
            logger.warning(f"[ToolAgent] {hint} error: {result['error']}")
            continue

        formatted = _format_tool_result(hint, result)
        if formatted:
            parts.append(formatted)

    context = "\n\n".join(parts)
    logger.info(f"[ToolAgent] Generated {len(parts)} tool contexts")
    return context


def _format_tool_result(tool_name: str, result: dict) -> str:
    """Format a tool result into a human-readable context string."""

    if tool_name == "spotify":
        if result.get("action") == "now_playing":
            if result.get("is_playing"):
                return (
                    f"🎵 NOW PLAYING:\n"
                    f"Track: {result['track']}\n"
                    f"Artist: {result['artist']}\n"
                    f"Album: {result['album']}"
                )
            else:
                return "🎵 Not currently playing anything."

        elif result.get("action") == "full_profile":
            source = result.get("source", "spotify")
            username = result.get("username", "")
            header = f"🎵 MUSIC PROFILE via Last.fm (@{username}) — last 30 days"
            parts = [header]

            # Currently / recently playing
            recent = result.get("recent", [])
            if recent:
                now = [t for t in recent if t.get("now_playing")]
                if now:
                    t = now[0]
                    parts.append(f"\n🔴 NOW PLAYING: {t['track']} — {t['artist']} (from '{t['album']}')"
                    )
                parts.append("\n🕒 RECENTLY PLAYED:")
                parts.append(f"{'#':<4} {'Track':<35} {'Artist':<25} {'Album':<25} {'When'}")
                parts.append("-" * 100)
                for i, t in enumerate([x for x in recent if not x.get("now_playing")][:5], 1):
                    parts.append(
                        f"{i:<4} {t['track'][:34]:<35} {t['artist'][:24]:<25} "
                        f"{t['album'][:24]:<25} {t['played_at'][:16]}"
                    )

            # Top Tracks
            top_tracks = result.get("top_tracks", [])
            if top_tracks:
                parts.append("\n📋 TOP TRACKS (by play count):")
                parts.append(f"{'#':<4} {'Track':<35} {'Artist':<30} {'Plays'}")
                parts.append("-" * 80)
                for t in top_tracks[:10]:
                    parts.append(f"{t['rank']:<4} {t['track'][:34]:<35} {t['artist'][:29]:<30} {t['playcount']}")

            # Top Artists
            top_artists = result.get("top_artists", [])
            if top_artists:
                parts.append("\n🎤 TOP ARTISTS (by play count):")
                parts.append(f"{'#':<4} {'Artist':<40} {'Plays'}")
                parts.append("-" * 55)
                for a in top_artists[:10]:
                    parts.append(f"{a['rank']:<4} {a['artist'][:39]:<40} {a['playcount']}")

            # Top Albums
            top_albums = result.get("top_albums", [])
            if top_albums:
                parts.append("\n💿 TOP ALBUMS (by play count):")
                parts.append(f"{'#':<4} {'Album':<35} {'Artist':<30} {'Plays'}")
                parts.append("-" * 78)
                for a in top_albums[:5]:
                    parts.append(f"{a['rank']:<4} {a['album'][:34]:<35} {a['artist'][:29]:<30} {a['playcount']}")

            return "\n".join(parts)


    elif tool_name == "youtube":
        videos = result.get("videos", [])
        if not videos:
            return "▶️ YOUTUBE — No recent videos."
        lines = ["▶️ YOUTUBE — Recent Videos:"]
        for v in videos[:5]:
            lines.append(f"  • {v['title']} — {v['url']}")
        return "\n".join(lines)

    elif tool_name == "github":
        if result.get("action") == "activity":
            activities = result.get("activities", [])
            if not activities:
                return "🐙 GITHUB — No recent activity."
            lines = [f"🐙 GITHUB — Recent Activity (@{result.get('username', '')}):"]
            for a in activities[:5]:
                lines.append(f"  • {a['description']} in {a['repo']}")
            return "\n".join(lines)
        elif result.get("action") == "repos":
            repos = result.get("repos", [])
            if not repos:
                return "🐙 GITHUB — No public repos."
            lines = [f"🐙 GITHUB — Top Repos (@{result.get('username', '')}):"]
            for r in repos[:5]:
                lang = f" [{r['language']}]" if r.get("language") else ""
                stars = f" ⭐{r['stars']}" if r.get("stars") else ""
                lines.append(f"  • {r['name']}{lang}{stars} — {r.get('description', '')}")
            return "\n".join(lines)

    return ""
