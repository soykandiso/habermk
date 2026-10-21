"""Phase 2: turn a short-lived Facebook user token into a Page token that does not expire.

    python scripts/fb_token.py

It asks for the App ID, the App Secret and the short-lived user token from the
Graph API Explorer (see docs/SETUP.md). Nothing is saved; copy the two printed
values into GitHub Secrets FB_PAGE_ID and FB_PAGE_TOKEN.
"""
from __future__ import annotations

import getpass
import sys

import httpx

GRAPH = "https://graph.facebook.com/v26.0"


def get(path: str, **params: str) -> dict:
    data = httpx.get(f"{GRAPH}/{path}", params=params, timeout=30).json()
    if "error" in data:
        sys.exit(f"Facebook error: {data['error'].get('message')}")
    return data


def main() -> int:
    app_id = input("App ID: ").strip()
    app_secret = getpass.getpass("App Secret (hidden): ").strip()
    short_token = getpass.getpass("Short-lived user token (hidden): ").strip()

    long_user = get("oauth/access_token", grant_type="fb_exchange_token", client_id=app_id,
                    client_secret=app_secret, fb_exchange_token=short_token)["access_token"]
    pages = get("me/accounts", access_token=long_user).get("data", [])
    if not pages:
        sys.exit("No Pages found. Did you grant pages_show_list for your Page?")
    for i, p in enumerate(pages):
        print(f"[{i}] {p['name']} (id {p['id']})")
    page = pages[int(input("Which Page? number: ") or 0)] if len(pages) > 1 else pages[0]

    info = get("debug_token", input_token=page["access_token"],
               access_token=f"{app_id}|{app_secret}")["data"]
    expires = "Never" if not info.get("expires_at") else str(info["expires_at"])
    print("\nSave these two values as GitHub Secrets:\n")
    print(f"FB_PAGE_ID    = {page['id']}")
    print(f"FB_PAGE_TOKEN = {page['access_token']}")
    print(f"\nToken valid: {info.get('is_valid')}  Expires: {expires}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
