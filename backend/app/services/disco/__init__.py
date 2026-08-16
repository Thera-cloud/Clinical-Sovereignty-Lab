"""GEO discoverability package — MASTER v4.0 + §18/§22 reference impl."""

from app.services.disco.engine import DiscoEngine
from app.services.disco.flags import disco_flag, DISCO_FLAGS

__all__ = ["DiscoEngine", "disco_flag", "DISCO_FLAGS"]
