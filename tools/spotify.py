"""
Spotify Tool — Now playing, recent tracks, top tracks, top artists, top albums.

Fallback chain (no Spotify Premium required after now_playing):
  now_playing → (403/204) → recent → (403) → full_profile

The 'full_profile' action fetches top tracks + top artists in parallel
and derives top albums from the track data.
"""

import asyncio
import logging
import base64

import httpx

from config import get_settings
from tools.base import BaseTool

logger = logging.getLogger(__name__)

SPOTIFY_TOKEN_URL    = "https://accounts.spotify.com/api/token"
SPOTIFY_NOW_PLAYING  = "https://api.spotify.com/v1/me/player/currently-playing"
SPOTIFY_RECENT       = "https://api.spotify.com/v1/me/player/recently-played"
SPOTIFY_TOP_TRACKS   = "https://api.spotify.com/v1/me/top/tracks"
SPOTIFY_TOP_ARTISTS  = "https://api.spotify.com/v1/me/top/artists"


class SpotifyTool(BaseTool):
    name = "spotify"
    description = "Get listening data: currently playing, recent history, top tracks, top artists, top albums"
    ttl = 60  # 60 second cache

    def __init__(self):
        super().__init__()
        self._access_token: str | None = None
        self._token_expiry: float = 0

    async def _refresh_access_token(self) -> str:
        """Refresh the Spotify access token using the stored refresh token."""
        settings = get_settings()
        if not settings.spotify_client_id or not settings.spotify_refresh_token:
            raise ValueError("Spotify credentials not configured")

        auth_header = base64.b64encode(
            f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
        ).decode()

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                SPOTIFY_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": settings.spotify_refresh_token,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        import time
        self._access_token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
        return self._access_token

    async def _get_token(self) -> str:
        import time
        if not self._access_token or time.time() >= self._token_expiry:
            return await self._refresh_access_token()
        return self._access_token

    # ── Private fetchers ──────────────────────────────────────────

    async def _get_top_tracks(self, client: httpx.AsyncClient, headers: dict, limit: int = 10) -> list[dict]:
        resp = await client.get(
            SPOTIFY_TOP_TRACKS,
            headers=headers,
            params={"limit": limit, "time_range": "short_term"},
        )
        resp.raise_for_status()
        tracks = []
        for i, item in enumerate(resp.json().get("items", []), 1):
            tracks.append({
                "rank": i,
                "track": item.get("name", "Unknown"),
                "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                "album": item.get("album", {}).get("name", "Unknown"),
                "url": item.get("external_urls", {}).get("spotify", ""),
                "popularity": item.get("popularity", 0),
            })
        return tracks

    async def _get_top_artists(self, client: httpx.AsyncClient, headers: dict, limit: int = 10) -> list[dict]:
        resp = await client.get(
            SPOTIFY_TOP_ARTISTS,
            headers=headers,
            params={"limit": limit, "time_range": "short_term"},
        )
        resp.raise_for_status()
        artists = []
        for i, item in enumerate(resp.json().get("items", []), 1):
            genres = item.get("genres", [])
            artists.append({
                "rank": i,
                "artist": item.get("name", "Unknown"),
                "genres": ", ".join(genres[:3]) if genres else "—",
                "popularity": item.get("popularity", 0),
                "url": item.get("external_urls", {}).get("spotify", ""),
            })
        return artists

    def _derive_top_albums(self, tracks: list[dict]) -> list[dict]:
        """Derive top albums from top tracks by counting occurrences."""
        seen = {}
        for t in tracks:
            key = t["album"]
            if key not in seen:
                seen[key] = {"album": key, "artist": t["artist"], "count": 0, "url": t["url"]}
            seen[key]["count"] += 1
        # Sort by how many top tracks are from this album
        albums = sorted(seen.values(), key=lambda x: x["count"], reverse=True)
        for i, a in enumerate(albums, 1):
            a["rank"] = i
        return albums[:5]

    # ── Public execute ────────────────────────────────────────────

    async def execute(self, action: str = "now_playing", limit: int = 10, **kwargs) -> dict:
        """
        Execute Spotify tool.

        Actions:
          'now_playing'  — currently playing track (needs Premium)
          'recent'       — recently played tracks (needs Premium)
          'full_profile' — top tracks + top artists + top albums (no Premium needed)

        Fallback chain:
          now_playing → 403/204 → recent → 403 → full_profile
        """
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:

            # ── Now Playing ─────────────────────────────────────
            if action == "now_playing":
                resp = await client.get(SPOTIFY_NOW_PLAYING, headers=headers)
                if resp.status_code == 204:
                    logger.info("[Spotify] Nothing playing, falling back to full_profile.")
                    action = "full_profile"
                elif resp.status_code == 403:
                    logger.warning("[Spotify] 403 on now_playing (no Premium), falling back to full_profile.")
                    action = "full_profile"
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    track = data.get("item", {})
                    return {
                        "tool": "spotify",
                        "action": "now_playing",
                        "is_playing": data.get("is_playing", False),
                        "track": track.get("name", "Unknown"),
                        "artist": ", ".join(a["name"] for a in track.get("artists", [])),
                        "album": track.get("album", {}).get("name", "Unknown"),
                        "url": track.get("external_urls", {}).get("spotify", ""),
                        "image": track.get("album", {}).get("images", [{}])[0].get("url", ""),
                    }

            # ── Recently Played ─────────────────────────────────
            if action == "recent":
                resp = await client.get(SPOTIFY_RECENT, headers=headers, params={"limit": min(limit, 10)})
                if resp.status_code == 403:
                    logger.warning("[Spotify] 403 on recently-played, falling back to full_profile.")
                    action = "full_profile"
                else:
                    resp.raise_for_status()
                    tracks = []
                    for item in resp.json().get("items", []):
                        t = item.get("track", {})
                        tracks.append({
                            "track": t.get("name", "Unknown"),
                            "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                            "played_at": item.get("played_at", ""),
                            "url": t.get("external_urls", {}).get("spotify", ""),
                        })
                    return {"tool": "spotify", "action": "recent", "tracks": tracks}

            # ── Full Profile: Top Tracks + Top Artists + Top Albums ──
            if action == "full_profile":
                top_tracks, top_artists = await asyncio.gather(
                    self._get_top_tracks(client, headers, limit),
                    self._get_top_artists(client, headers, limit),
                    return_exceptions=True,
                )

                if isinstance(top_tracks, Exception):
                    logger.error(f"[Spotify] Top tracks failed: {top_tracks}")
                    top_tracks = []
                if isinstance(top_artists, Exception):
                    logger.error(f"[Spotify] Top artists failed: {top_artists}")
                    top_artists = []

                top_albums = self._derive_top_albums(top_tracks) if top_tracks else []

                return {
                    "tool": "spotify",
                    "action": "full_profile",
                    "top_tracks": top_tracks,
                    "top_artists": top_artists,
                    "top_albums": top_albums,
                }

        return {"tool": "spotify", "error": f"Unknown action: {action}"}
