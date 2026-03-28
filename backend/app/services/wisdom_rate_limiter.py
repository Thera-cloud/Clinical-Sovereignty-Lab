"""
Wisdom Rate Limiter — Phase 5 Security Hardening.

In-memory rate limiting for community wisdom submissions, crystal operations,
semantic search, and token sharing. Thread-safe singleton.
"""

import logging
import time
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Action types and default limits: (max_per_window, window_seconds)
_ACTION_LIMITS = {
    "submit": (10, 60),
    "crystal_create": (5, 60),
    "search": (30, 60),
    "share": (3, 60),
}

# Max window for cleanup (longest window across all action types)
_MAX_WINDOW_SECONDS = 60


class WisdomRateLimiter:
    """
    Thread-safe in-memory rate limiter for wisdom and crystal operations.
    Tracks timestamps per (user_id, action) pair.
    """

    _instance: Optional["WisdomRateLimiter"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        # {user_id: {action: [timestamp, ...]}}
        self._tracking: Dict[str, Dict[str, List[float]]] = {}
        self._tracking_lock = threading.RLock()

    @classmethod
    def get(cls) -> "WisdomRateLimiter":
        """Return the global singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _get_limits(self, action: str) -> tuple:
        """Return (max_per_window, window_seconds) for the action."""
        return _ACTION_LIMITS.get(action, (10, 60))

    def check_rate(
        self,
        user_id: str,
        action: str = "submit",
        max_per_window: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> bool:
        """
        Returns True if the action is allowed, False if rate exceeded.
        Uses default limits for the action unless overridden.
        """
        if max_per_window is None or window_seconds is None:
            default_max, default_window = _ACTION_LIMITS.get(action, (10, 60))
            max_per_window = max_per_window or default_max
            window_seconds = window_seconds or default_window

        with self._tracking_lock:
            self._cleanup_expired()
            now = time.monotonic()
            cutoff = now - window_seconds

            user_data = self._tracking.get(user_id, {})
            timestamps = user_data.get(action, [])

            # Count timestamps within the window
            in_window = [t for t in timestamps if t >= cutoff]
            count = len(in_window)

            return count < max_per_window

    def record_action(self, user_id: str, action: str = "submit") -> None:
        """Record an action timestamp for the user."""
        with self._tracking_lock:
            if user_id not in self._tracking:
                self._tracking[user_id] = {}
            if action not in self._tracking[user_id]:
                self._tracking[user_id][action] = []
            self._tracking[user_id][action].append(time.monotonic())
            self._cleanup_expired()

    def get_rate_info(
        self,
        user_id: str,
        action: str = "submit",
    ) -> Dict:
        """
        Returns current rate info: count in window, time until next allowed, etc.
        """
        max_per_window, window_seconds = self._get_limits(action)

        with self._tracking_lock:
            self._cleanup_expired()
            now = time.monotonic()
            cutoff = now - window_seconds

            user_data = self._tracking.get(user_id, {})
            timestamps = user_data.get(action, [])
            in_window = [t for t in timestamps if t >= cutoff]
            count = len(in_window)

            allowed = count < max_per_window
            time_until_next_allowed = 0.0

            if not allowed and in_window:
                # Oldest entry in window will expire first
                oldest = min(in_window)
                time_until_next_allowed = max(0, (oldest + window_seconds) - now)

            return {
                "user_id": user_id,
                "action": action,
                "count_in_window": count,
                "max_per_window": max_per_window,
                "window_seconds": window_seconds,
                "allowed": allowed,
                "time_until_next_allowed_seconds": round(time_until_next_allowed, 1),
            }

    def _cleanup_expired(self) -> None:
        """Remove timestamps older than the max window. Caller must hold _tracking_lock."""
        now = time.monotonic()
        cutoff = now - _MAX_WINDOW_SECONDS

        to_remove_user: List[str] = []
        to_remove_action: List[tuple] = []

        for user_id, actions in self._tracking.items():
            for action, timestamps in actions.items():
                # Keep only recent timestamps
                valid = [t for t in timestamps if t >= cutoff]
                if valid:
                    self._tracking[user_id][action] = valid
                else:
                    to_remove_action.append((user_id, action))
            if not self._tracking[user_id]:
                to_remove_user.append(user_id)

        for user_id, action in to_remove_action:
            if user_id in self._tracking and action in self._tracking[user_id]:
                del self._tracking[user_id][action]
        for user_id in to_remove_user:
            if user_id in self._tracking:
                del self._tracking[user_id]
