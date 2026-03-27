"""pub.dev package metadata lookup (async, rate-limited)."""
import asyncio
from typing import Optional

import httpx

_PUBDEV_API = "https://pub.dev/api/packages"


def _extract_git_url(pubspec: dict) -> Optional[str]:
    return pubspec.get("repository") or None


async def _lookup_one(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, name: str) -> dict:
    base = {"name": name, "pub_url": f"https://pub.dev/packages/{name}"}
    async with semaphore:
        try:
            resp = await client.get(f"{_PUBDEV_API}/{name}", timeout=15)
            await asyncio.sleep(0.2)  # stay under 5 req/s
            if resp.status_code == 404:
                return {**base, "git_url": None, "found": False, "error": "Package not found on pub.dev"}
            resp.raise_for_status()
            pubspec = resp.json().get("latest", {}).get("pubspec", {})
            git_url = _extract_git_url(pubspec)
            return {
                **base,
                "git_url": git_url,
                "found": True,
                "error": None,
            }
        except httpx.HTTPError as exc:
            return {**base, "git_url": None, "found": False, "error": str(exc)}


async def lookup(names: list[str]) -> list[dict]:
    """
    Query pub.dev for a list of package names.
    Returns [{name, git_url, pub_url, found, error}] in the same order.
    Concurrent, limited to 5 simultaneous requests.
    """
    clean = [n.strip() for n in names if n.strip()]
    if not clean:
        return []
    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient() as client:
        tasks = [_lookup_one(client, semaphore, name) for name in clean]
        return list(await asyncio.gather(*tasks))
