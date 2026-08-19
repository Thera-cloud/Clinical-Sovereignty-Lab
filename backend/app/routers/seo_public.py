"""Public crawler policy for the API origin (api.sovereignsanctuary.net)."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["seo-public"])

_API_ROBOTS = "User-agent: *\nDisallow: /\n"
_NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


@router.get("/robots.txt", response_class=PlainTextResponse)
async def api_robots_txt():
    return PlainTextResponse(_API_ROBOTS, headers=_NOINDEX)
