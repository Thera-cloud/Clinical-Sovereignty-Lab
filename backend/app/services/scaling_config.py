"""
Auto-Scaling Ladder — Phase 8 infrastructure scaling levels.

Each level defines the active inference providers. The SCALING_LEVEL env var
selects the current level. The inference router consults get_active_providers()
to decide which providers are eligible for a given request.
"""

import os

SCALING_LEVELS = {
    1: {
        "name": "Sovereign Solo",
        "providers": ["sovereign"],
        "description": "Single Hetzner node, 3 models",
    },
    2: {
        "name": "Workers Overflow",
        "providers": ["sovereign", "workers_ai"],
        "description": "Add Workers AI for LOCKED/PROMOTED overflow",
    },
    3: {
        "name": "Twin-Helix",
        "providers": ["sovereign", "digitalocean", "workers_ai"],
        "description": "Add DigitalOcean 8B node",
    },
    4: {
        "name": "Home GPU",
        "providers": ["home_gpu", "sovereign", "digitalocean", "workers_ai"],
        "description": "Add home 70B GPU for clinical",
    },
    5: {
        "name": "Multi-GPU",
        "providers": ["home_gpu", "sovereign", "digitalocean", "workers_ai", "azure"],
        "description": "Full fleet with Azure safety net",
    },
    6: {
        "name": "Elastic",
        "providers": ["home_gpu", "sovereign", "digitalocean", "workers_ai", "azure"],
        "description": "Auto-scale based on queue depth",
    },
}

CURRENT_LEVEL = int(os.getenv("SCALING_LEVEL", "1"))


def get_active_providers():
    """Return the list of providers enabled at the current scaling level."""
    level = SCALING_LEVELS.get(CURRENT_LEVEL, SCALING_LEVELS[1])
    return level["providers"]


def get_current_level_info():
    """Return name, description, and providers for the current scaling level."""
    level = SCALING_LEVELS.get(CURRENT_LEVEL, SCALING_LEVELS[1])
    return {
        "level": CURRENT_LEVEL,
        **level,
    }
