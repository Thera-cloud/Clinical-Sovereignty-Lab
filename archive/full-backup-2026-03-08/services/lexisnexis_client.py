"""
LexisNexis Protege Web Services API Client (OAuth 2.0)

Provides search-only access to LexisNexis content for JUDGE DOJO coaches.
Judge Nate uses this to search case law, statutes, and legal content
on behalf of the lawyer (search-only, no personal case access).

Required env:
  - LEXISNEXIS_CLIENT_ID
  - LEXISNEXIS_CLIENT_SECRET

Reference: https://dev.lexisnexis.com/
"""

from __future__ import annotations

import os
import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class LexisToken:
    access_token: str
    expires_at: datetime.datetime  # UTC

    def is_valid(self, skew_seconds: int = 60) -> bool:
        return datetime.datetime.utcnow() + datetime.timedelta(seconds=skew_seconds) < self.expires_at


class LexisNexisClient:
    """
    LexisNexis Protege Web Services API client.

    Uses OAuth 2.0 client credentials flow for authentication.
    Provides search-only access — no access to lawyer's personal cases or account data.
    """

    # LexisNexis API endpoints (Protege Web Services)
    TOKEN_URL = "https://auth-api.lexisnexis.com/oauth/v2/token"
    SEARCH_URL = "https://services-api.lexisnexis.com/v1/search"
    CASE_DETAIL_URL = "https://services-api.lexisnexis.com/v1/documents"
    STATUTES_URL = "https://services-api.lexisnexis.com/v1/search"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
    ) -> None:
        self.client_id = client_id or os.getenv("LEXISNEXIS_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("LEXISNEXIS_CLIENT_SECRET", "")
        self._token: Optional[LexisToken] = None

        if not self.client_id or not self.client_secret:
            print("[LexisNexis] WARNING: Missing LEXISNEXIS_CLIENT_ID or LEXISNEXIS_CLIENT_SECRET")

    async def authenticate(self) -> str:
        """Get or refresh OAuth 2.0 access token via client credentials flow."""
        if self._token and self._token.is_valid():
            return self._token.access_token

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "http://oauth.lexisnexis.com/all",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )

            if resp.status_code != 200:
                raise Exception(f"LexisNexis auth failed: {resp.status_code} - {resp.text}")

            data = resp.json()
            access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)

            self._token = LexisToken(
                access_token=access_token,
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in),
            )

            print(f"[LexisNexis] Token acquired, expires in {expires_in}s")
            return access_token

    async def _authed_request(self, method: str, url: str, **kwargs) -> Dict:
        """Make an authenticated request to the LexisNexis API."""
        token = await self.authenticate()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        headers.update(kwargs.pop("headers", {}))

        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method, url, headers=headers, timeout=30.0, **kwargs
            )

            if resp.status_code == 401:
                # Token expired, retry once
                self._token = None
                token = await self.authenticate()
                headers["Authorization"] = f"Bearer {token}"
                resp = await client.request(
                    method, url, headers=headers, timeout=30.0, **kwargs
                )

            if resp.status_code != 200:
                return {"error": f"LexisNexis API error: {resp.status_code}", "detail": resp.text}

            return resp.json()

    async def search_cases(
        self,
        query: str,
        jurisdiction: str = "",
        date_range: str = "",
        max_results: int = 10,
    ) -> Dict:
        """Search case law through LexisNexis.

        Args:
            query: Search query (natural language or boolean)
            jurisdiction: e.g., "federal", "CA", "NY", "TX"
            date_range: e.g., "last_year", "last_5_years", "2020-2025"
            max_results: Maximum number of results to return

        Returns:
            dict with 'results' list containing case summaries
        """
        if not self.client_id:
            return {
                "error": "LexisNexis not configured",
                "results": [],
                "message": "LEXISNEXIS_CLIENT_ID and LEXISNEXIS_CLIENT_SECRET must be set in .env"
            }

        search_body = {
            "$search": query,
            "$top": max_results,
            "$filter": "contenttype eq 'Cases'",
        }

        if jurisdiction:
            search_body["$filter"] += f" and jurisdiction eq '{jurisdiction}'"

        if date_range:
            if date_range == "last_year":
                cutoff = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
                search_body["$filter"] += f" and date ge {cutoff}"
            elif date_range == "last_5_years":
                cutoff = (datetime.datetime.now() - datetime.timedelta(days=1825)).strftime("%Y-%m-%d")
                search_body["$filter"] += f" and date ge {cutoff}"

        try:
            data = await self._authed_request("POST", self.SEARCH_URL, json=search_body)

            if data.get("error"):
                return data

            results = []
            for item in data.get("value", []):
                results.append({
                    "case_id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "citation": item.get("citation", ""),
                    "court": item.get("court", ""),
                    "date": item.get("date", ""),
                    "summary": item.get("overview", item.get("snippet", ""))[:500],
                    "relevance_score": item.get("score", 0),
                })

            return {
                "query": query,
                "jurisdiction": jurisdiction,
                "total_results": data.get("@odata.count", len(results)),
                "results": results,
            }
        except Exception as e:
            return {"error": str(e), "results": []}

    async def get_case_detail(self, case_id: str) -> Dict:
        """Get the full text and details of a specific case.

        Args:
            case_id: The LexisNexis document/case identifier

        Returns:
            dict with case title, full text, citations, and metadata
        """
        if not self.client_id:
            return {"error": "LexisNexis not configured"}

        try:
            url = f"{self.CASE_DETAIL_URL}/{case_id}"
            data = await self._authed_request("GET", url)

            if data.get("error"):
                return data

            return {
                "case_id": case_id,
                "title": data.get("title", ""),
                "citation": data.get("citation", ""),
                "court": data.get("court", ""),
                "date": data.get("date", ""),
                "full_text": data.get("body", data.get("content", "")),
                "headnotes": data.get("headnotes", []),
                "citations_referenced": data.get("citedBy", []),
            }
        except Exception as e:
            return {"error": str(e)}

    async def search_statutes(
        self,
        query: str,
        jurisdiction: str = "",
        max_results: int = 10,
    ) -> Dict:
        """Search statutes and legislation through LexisNexis.

        Args:
            query: Search query
            jurisdiction: e.g., "federal", "CA", "NY"
            max_results: Maximum results

        Returns:
            dict with 'results' list
        """
        if not self.client_id:
            return {"error": "LexisNexis not configured", "results": []}

        search_body = {
            "$search": query,
            "$top": max_results,
            "$filter": "contenttype eq 'Statutes and Legislation'",
        }

        if jurisdiction:
            search_body["$filter"] += f" and jurisdiction eq '{jurisdiction}'"

        try:
            data = await self._authed_request("POST", self.STATUTES_URL, json=search_body)

            if data.get("error"):
                return data

            results = []
            for item in data.get("value", []):
                results.append({
                    "statute_id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "citation": item.get("citation", ""),
                    "jurisdiction": item.get("jurisdiction", ""),
                    "summary": item.get("overview", item.get("snippet", ""))[:500],
                })

            return {
                "query": query,
                "jurisdiction": jurisdiction,
                "results": results,
            }
        except Exception as e:
            return {"error": str(e), "results": []}


# Singleton instance
_lexis_client: Optional[LexisNexisClient] = None


def get_lexisnexis_client() -> LexisNexisClient:
    """Get or create the singleton LexisNexisClient."""
    global _lexis_client
    if _lexis_client is None:
        _lexis_client = LexisNexisClient()
    return _lexis_client
