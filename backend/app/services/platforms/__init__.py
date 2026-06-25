"""
LITTLE NATE — SkyEye Platform Adapter Registry
Central registry for all social media platform adapters.

Usage:
    from app.services.platforms import get_adapter, get_all_adapters

    adapter = get_adapter("tiktok", db_pool)
    all_adapters = get_all_adapters(db_pool)
"""

import logging
from typing import Dict, Optional

from app.services.skyeye_platform_base import SocialPlatformAdapter

logger = logging.getLogger("skyeye.platforms")

# Lazy imports to avoid loading SDKs that aren't installed
_ADAPTER_MAP = {
    "tiktok":               "app.services.platforms.tiktok.TikTokAdapter",
    "instagram":            "app.services.platforms.instagram.InstagramAdapter",
    "youtube":              "app.services.platforms.youtube.YouTubeAdapter",
    "reddit":               "app.services.platforms.reddit.RedditAdapter",
    "linkedin":             "app.services.platforms.linkedin.LinkedInAdapter",
    "linkedin_company":     "app.services.platforms.linkedin.LinkedInCompanyAdapter",
    "linkedin_community":   "app.services.platforms.linkedin.LinkedInCommunityAdapter",
    "facebook":             "app.services.platforms.facebook.FacebookAdapter",
    "pinterest":            "app.services.platforms.pinterest.PinterestAdapter",
    "x":                    "app.services.platforms.x_twitter.XTwitterAdapter",
}

# Cache instantiated adapters per db_pool identity
_adapter_cache: Dict[str, SocialPlatformAdapter] = {}


def _import_adapter_class(dotted_path: str):
    """Dynamically import an adapter class from its dotted path."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_adapter(platform: str, db_pool,
                rate_limit_seconds: float = 10.0) -> Optional[SocialPlatformAdapter]:
    """
    Get a platform adapter instance by name.

    Returns None if the platform is unknown or the adapter can't be loaded
    (e.g., missing SDK dependency). Never crashes — graceful degradation.

    Args:
        platform: Platform name (e.g., 'tiktok', 'instagram')
        db_pool: asyncpg connection pool
        rate_limit_seconds: Minimum seconds between API calls

    Returns:
        SocialPlatformAdapter instance or None
    """
    platform = platform.lower().strip()

    # Check cache first
    cache_key = f"{platform}_{id(db_pool)}"
    if cache_key in _adapter_cache:
        return _adapter_cache[cache_key]

    dotted_path = _ADAPTER_MAP.get(platform)
    if not dotted_path:
        logger.warning(f"Unknown platform: {platform}")
        return None

    try:
        adapter_class = _import_adapter_class(dotted_path)
        adapter = adapter_class(db_pool=db_pool, rate_limit_seconds=rate_limit_seconds)
        _adapter_cache[cache_key] = adapter
        logger.info(f"Loaded adapter for {platform}: {adapter_class.__name__}")
        return adapter
    except ImportError as e:
        logger.warning(f"Cannot load adapter for {platform} (missing dependency): {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to instantiate adapter for {platform}: {e}")
        return None


def get_all_adapters(db_pool,
                     rate_limit_seconds: float = 10.0) -> Dict[str, SocialPlatformAdapter]:
    """
    Get adapter instances for all known platforms.
    Only returns adapters that loaded successfully.

    Returns:
        Dict mapping platform name to adapter instance
    """
    adapters = {}
    for platform in _ADAPTER_MAP:
        adapter = get_adapter(platform, db_pool, rate_limit_seconds)
        if adapter is not None:
            adapters[platform] = adapter
    return adapters


def get_supported_platforms() -> list:
    """Return list of all supported platform names."""
    return list(_ADAPTER_MAP.keys())


def clear_cache():
    """Clear the adapter cache. Useful for testing."""
    _adapter_cache.clear()
