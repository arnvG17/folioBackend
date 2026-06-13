"""
Base Tool — Abstract base class with TTL caching.
"""

import time
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Abstract base class for all tool integrations."""

    name: str = "base_tool"
    description: str = "Base tool"
    ttl: int = 60  # Cache TTL in seconds

    def __init__(self):
        self._cache: dict[str, Any] = {}
        self._cache_timestamps: dict[str, float] = {}

    def _get_cached(self, key: str) -> Any | None:
        """Return cached value if still within TTL."""
        if key in self._cache:
            age = time.time() - self._cache_timestamps.get(key, 0)
            if age < self.ttl:
                logger.debug(f"[{self.name}] Cache hit for '{key}' (age={age:.1f}s)")
                return self._cache[key]
            else:
                # Expired
                del self._cache[key]
                del self._cache_timestamps[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        """Store value in cache with current timestamp."""
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()

    @abstractmethod
    async def execute(self, **kwargs) -> dict:
        """Execute the tool and return results."""
        ...

    async def run(self, **kwargs) -> dict:
        """Run with caching. Override cache_key generation if needed."""
        cache_key = f"{self.name}:{str(sorted(kwargs.items()))}"

        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            result = await self.execute(**kwargs)
            self._set_cached(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"[{self.name}] Tool execution error: {e}")
            return {"error": str(e), "tool": self.name}
