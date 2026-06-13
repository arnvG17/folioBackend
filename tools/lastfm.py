"""
Last.fm Tool — Recent tracks, top tracks, top artists, top albums.

No OAuth, no Premium required. Just an API key + username.
All data fetched in parallel for a rich music profile.
"""

import asyncio
import logging

import httpx

from config import get_settings
from tools.base import BaseTool

logger = logging.getLogger(__name__)

LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"


class LastFmTool(BaseTool):
    name = "spotify"  # keeps existing router hints ("spotify" key) working
    description = "Get music listening data: recent tracks, top tracks, top artists, top albums via Last.fm"
    ttl = 60  # 60-second cache

    def _params(self, method: str, extra: dict) -> dict:
        settings = get_settings()
        return {
            "method": method,
            "user": settings.lastfm_username,
            "api_key": settings.lastfm_api_key,
            "format": "json",
            **extra,
        }

    async def _recent_tracks(self, client: httpx.AsyncClient, limit: int = 5) -> list[dict]:
        resp = await client.get(LASTFM_BASE, params=self._params("user.getrecenttracks", {"limit": limit}))
        resp.raise_for_status()
        items = resp.json().get("recenttracks", {}).get("track", [])
        tracks = []
        for item in items[:limit]:
            # Skip the currently-playing marker entry if present
            attr = item.get("@attr", {})
            is_now = attr.get("nowplaying") == "true"
            tracks.append({
                "track": item.get("name", "Unknown"),
                "artist": item.get("artist", {}).get("#text", "Unknown"),
                "album": item.get("album", {}).get("#text", "—"),
                "now_playing": is_now,
                "played_at": item.get("date", {}).get("#text", "Now") if not is_now else "Now",
                "url": item.get("url", ""),
            })
        return tracks

    async def _top_tracks(self, client: httpx.AsyncClient, limit: int = 10) -> list[dict]:
        resp = await client.get(LASTFM_BASE, params=self._params("user.gettoptracks", {"limit": limit, "period": "1month"}))
        resp.raise_for_status()
        items = resp.json().get("toptracks", {}).get("track", [])
        tracks = []
        for i, item in enumerate(items[:limit], 1):
            tracks.append({
                "rank": i,
                "track": item.get("name", "Unknown"),
                "artist": item.get("artist", {}).get("name", "Unknown"),
                "playcount": item.get("playcount", "0"),
                "url": item.get("url", ""),
            })
        return tracks

    async def _top_artists(self, client: httpx.AsyncClient, limit: int = 10) -> list[dict]:
        resp = await client.get(LASTFM_BASE, params=self._params("user.gettopartists", {"limit": limit, "period": "1month"}))
        resp.raise_for_status()
        items = resp.json().get("topartists", {}).get("artist", [])
        artists = []
        for i, item in enumerate(items[:limit], 1):
            artists.append({
                "rank": i,
                "artist": item.get("name", "Unknown"),
                "playcount": item.get("playcount", "0"),
                "url": item.get("url", ""),
            })
        return artists

    async def _top_albums(self, client: httpx.AsyncClient, limit: int = 10) -> list[dict]:
        resp = await client.get(LASTFM_BASE, params=self._params("user.gettopalbums", {"limit": limit, "period": "1month"}))
        resp.raise_for_status()
        items = resp.json().get("topalbums", {}).get("album", [])
        albums = []
        for i, item in enumerate(items[:limit], 1):
            albums.append({
                "rank": i,
                "album": item.get("name", "Unknown"),
                "artist": item.get("artist", {}).get("name", "Unknown"),
                "playcount": item.get("playcount", "0"),
                "url": item.get("url", ""),
            })
        return albums

    async def execute(self, **kwargs) -> dict:
        """
        Fetch a full music profile: recent, top tracks, top artists, top albums — all in parallel.
        """
        settings = get_settings()
        if not settings.lastfm_api_key or not settings.lastfm_username:
            raise ValueError("Last.fm credentials not configured (LASTFM_API_KEY, LASTFM_USERNAME)")

        async with httpx.AsyncClient(timeout=10.0) as client:
            recent, top_tracks, top_artists, top_albums = await asyncio.gather(
                self._recent_tracks(client, limit=5),
                self._top_tracks(client, limit=10),
                self._top_artists(client, limit=10),
                self._top_albums(client, limit=5),
                return_exceptions=True,
            )

        def _safe(result, fallback):
            return fallback if isinstance(result, Exception) else result

        if isinstance(recent, Exception):
            logger.error(f"[LastFm] recent_tracks failed: {recent}")
        if isinstance(top_tracks, Exception):
            logger.error(f"[LastFm] top_tracks failed: {top_tracks}")
        if isinstance(top_artists, Exception):
            logger.error(f"[LastFm] top_artists failed: {top_artists}")
        if isinstance(top_albums, Exception):
            logger.error(f"[LastFm] top_albums failed: {top_albums}")

        return {
            "tool": "spotify",
            "action": "full_profile",
            "source": "lastfm",
            "username": settings.lastfm_username,
            "recent": _safe(recent, []),
            "top_tracks": _safe(top_tracks, []),
            "top_artists": _safe(top_artists, []),
            "top_albums": _safe(top_albums, []),
        }
