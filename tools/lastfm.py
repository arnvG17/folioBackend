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

    async def _user_info(self, client: httpx.AsyncClient) -> dict:
        try:
            resp = await client.get(LASTFM_BASE, params=self._params("user.getinfo", {}))
            if resp.status_code == 200:
                user = resp.json().get("user", {})
                return {
                    "playcount": user.get("playcount", "0"),
                    "registered_unixtime": int(user.get("registered", {}).get("unixtime", 0)),
                    "realname": user.get("realname", ""),
                    "country": user.get("country", ""),
                }
        except Exception as e:
            logger.error(f"[LastFm] user_info failed: {e}")
        return {"playcount": "0", "registered_unixtime": 0, "realname": "", "country": ""}

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

    async def _top_tracks(self, client: httpx.AsyncClient, period: str = "1month", limit: int = 10) -> list[dict]:
        resp = await client.get(LASTFM_BASE, params=self._params("user.gettoptracks", {"limit": limit, "period": period}))
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

    async def _top_artists(self, client: httpx.AsyncClient, period: str = "1month", limit: int = 10) -> list[dict]:
        resp = await client.get(LASTFM_BASE, params=self._params("user.gettopartists", {"limit": limit, "period": period}))
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

    async def _top_albums(self, client: httpx.AsyncClient, period: str = "1month", limit: int = 10) -> list[dict]:
        resp = await client.get(LASTFM_BASE, params=self._params("user.gettopalbums", {"limit": limit, "period": period}))
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
        Fetch a full music profile including user details and top lists across multiple periods.
        """
        settings = get_settings()
        if not settings.lastfm_api_key or not settings.lastfm_username:
            raise ValueError("Last.fm credentials not configured (LASTFM_API_KEY, LASTFM_USERNAME)")

        async with httpx.AsyncClient(timeout=10.0) as client:
            (
                user_info,
                recent,
                top_tracks_4weeks,
                top_tracks_6months,
                top_tracks_12months,
                top_artists_4weeks,
                top_artists_6months,
                top_artists_12months,
                top_albums_4weeks,
                top_albums_6months,
                top_albums_12months,
            ) = await asyncio.gather(
                self._user_info(client),
                self._recent_tracks(client, limit=5),
                self._top_tracks(client, period="1month", limit=10),
                self._top_tracks(client, period="6month", limit=10),
                self._top_tracks(client, period="12month", limit=10),
                self._top_artists(client, period="1month", limit=10),
                self._top_artists(client, period="6month", limit=10),
                self._top_artists(client, period="12month", limit=10),
                self._top_albums(client, period="1month", limit=5),
                self._top_albums(client, period="6month", limit=5),
                self._top_albums(client, period="12month", limit=5),
                return_exceptions=True,
            )

        def _safe(result, fallback):
            return fallback if isinstance(result, Exception) else result

        # Log exceptions if any failed
        for task_name, task_res in [
            ("user_info", user_info), ("recent", recent),
            ("tracks_4w", top_tracks_4weeks), ("tracks_6m", top_tracks_6months), ("tracks_12m", top_tracks_12months),
            ("artists_4w", top_artists_4weeks), ("artists_6m", top_artists_6months), ("artists_12m", top_artists_12months),
            ("albums_4w", top_albums_4weeks), ("albums_6m", top_albums_6months), ("albums_12m", top_albums_12months),
        ]:
            if isinstance(task_res, Exception):
                logger.error(f"[LastFm] {task_name} task failed: {task_res}")

        return {
            "tool": "spotify",
            "action": "full_profile",
            "source": "lastfm",
            "username": settings.lastfm_username,
            "user_info": _safe(user_info, {"playcount": "0", "registered_unixtime": 0, "realname": "", "country": ""}),
            "recent": _safe(recent, []),
            "top_tracks_4weeks": _safe(top_tracks_4weeks, []),
            "top_tracks_6months": _safe(top_tracks_6months, []),
            "top_tracks_12months": _safe(top_tracks_12months, []),
            "top_artists_4weeks": _safe(top_artists_4weeks, []),
            "top_artists_6months": _safe(top_artists_6months, []),
            "top_artists_12months": _safe(top_artists_12months, []),
            "top_albums_4weeks": _safe(top_albums_4weeks, []),
            "top_albums_6months": _safe(top_albums_6months, []),
            "top_albums_12months": _safe(top_albums_12months, []),
        }
