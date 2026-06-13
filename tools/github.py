"""
GitHub Tool — Activity feed and repos via GitHub API.
"""

import logging

import httpx

from config import get_settings
from tools.base import BaseTool

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubTool(BaseTool):
    name = "github"
    description = "Get GitHub activity feed and repositories"
    ttl = 120  # 2 minute cache

    def _get_headers(self) -> dict:
        settings = get_settings()
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "portfolio-agent",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        return headers

    async def execute(self, action: str = "activity", limit: int = 10, **kwargs) -> dict:
        """
        Execute GitHub tool.
        Actions: 'activity' | 'repos'
        """
        settings = get_settings()

        if not settings.github_username:
            return {"tool": "github", "error": "GitHub username not configured"}

        headers = self._get_headers()

        async with httpx.AsyncClient() as client:
            if action == "activity":
                resp = await client.get(
                    f"{GITHUB_API_BASE}/users/{settings.github_username}/events",
                    headers=headers,
                    params={"per_page": min(limit, 30)},
                )
                resp.raise_for_status()
                events = resp.json()

                activities = []
                for event in events[:limit]:
                    repo = event.get("repo", {}).get("name", "")
                    event_type = event.get("type", "")
                    created = event.get("created_at", "")

                    # Human-readable event description
                    desc = _format_event(event_type, event.get("payload", {}))

                    activities.append({
                        "type": event_type,
                        "repo": repo,
                        "description": desc,
                        "created_at": created,
                        "url": f"https://github.com/{repo}",
                    })

                return {
                    "tool": "github",
                    "action": "activity",
                    "username": settings.github_username,
                    "activities": activities,
                }

            elif action == "repos":
                resp = await client.get(
                    f"{GITHUB_API_BASE}/users/{settings.github_username}/repos",
                    headers=headers,
                    params={
                        "sort": "updated",
                        "per_page": min(limit, 10),
                        "direction": "desc",
                    },
                )
                resp.raise_for_status()
                repos_data = resp.json()

                repos = []
                for repo in repos_data[:limit]:
                    repos.append({
                        "name": repo.get("name", ""),
                        "description": repo.get("description", ""),
                        "language": repo.get("language", ""),
                        "stars": repo.get("stargazers_count", 0),
                        "forks": repo.get("forks_count", 0),
                        "url": repo.get("html_url", ""),
                        "updated_at": repo.get("updated_at", ""),
                    })

                return {
                    "tool": "github",
                    "action": "repos",
                    "username": settings.github_username,
                    "repos": repos,
                }

        return {"tool": "github", "error": f"Unknown action: {action}"}


def _format_event(event_type: str, payload: dict) -> str:
    """Convert GitHub event type to human-readable description."""
    descriptions = {
        "PushEvent": f"Pushed {payload.get('size', 0)} commit(s)",
        "CreateEvent": f"Created {payload.get('ref_type', 'repository')}",
        "DeleteEvent": f"Deleted {payload.get('ref_type', 'branch')}",
        "IssuesEvent": f"{payload.get('action', 'updated').capitalize()} an issue",
        "PullRequestEvent": f"{payload.get('action', 'updated').capitalize()} a pull request",
        "WatchEvent": "Starred a repository",
        "ForkEvent": "Forked a repository",
        "ReleaseEvent": f"Published release {payload.get('release', {}).get('tag_name', '')}",
        "IssueCommentEvent": "Commented on an issue",
    }
    return descriptions.get(event_type, event_type.replace("Event", ""))
