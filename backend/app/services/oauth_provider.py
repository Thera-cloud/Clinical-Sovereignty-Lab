"""OAuthProvider — external API consumer OAuth 2.0 (request-response). Stub — full implementation pending"""

import logging

logger = logging.getLogger(__name__)


class OAuthProvider:
    """Stub — full implementation pending"""

    def __init__(self, db_pool=None, redis_client=None):
        self.db_pool = db_pool
        self.redis_client = redis_client
        self._clients = {}

    async def load_clients(self):
        logger.info("OAuthProvider.load_clients (stub — no clients loaded)")
