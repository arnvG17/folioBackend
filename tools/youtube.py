"""
YouTube Tool — Recent videos via YouTube Data API v3.
"""

import logging

import httpx

from config import get_settings
from tools.base import BaseTool

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeTool(BaseTool):
    name = "youtube"
    description = "Get recent YouTube videos from channel"
    ttl = 300  # 5 minute cache

    async def execute(self, limit: int = 5, **kwargs) -> dict:
        """Fetch recent uploads from the configured YouTube channel."""
        settings = get_settings()

        if not settings.youtube_api_key or not settings.youtube_channel_id:
            return {
                "tool": "youtube",
                "error": "YouTube API not configured",
                "videos": [],
            }

        async with httpx.AsyncClient() as client:
            # Search for recent uploads
            resp = await client.get(
                YOUTUBE_SEARCH_URL,
                params={
                    "key": settings.youtube_api_key,
                    "channelId": settings.youtube_channel_id,
                    "part": "snippet",
                    "order": "date",
                    "maxResults": min(limit, 10),
                    "type": "video",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        videos = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId", "")
            videos.append({
                "title": snippet.get("title", "Untitled"),
                "description": snippet.get("description", "")[:200],
                "published_at": snippet.get("publishedAt", ""),
                "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "url": f"https://youtube.com/watch?v={video_id}" if video_id else "",
            })

        return {
            "tool": "youtube",
            "channel_id": settings.youtube_channel_id,
            "videos": videos,
        }
