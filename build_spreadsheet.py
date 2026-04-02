#!/usr/bin/env python3
"""
Build a spreadsheet of HollowPoiint's horror games with Steam store data.

Reads horror_games_data.json, looks up each game on Steam, and outputs
a CSV with: game name, video count, Steam link, price, genres, developer,
AAA/indie classification, Steam Deck compatibility, release date, reviews, etc.

Requirements:
  pip install requests

Usage:
  python3 build_spreadsheet.py
  python3 build_spreadsheet.py --input horror_games_data.json --output horror_games.csv
"""

import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import requests
except ImportError:
    print("Installing requests...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# ---------------------------------------------------------------------------
# Steam API helpers
# ---------------------------------------------------------------------------

# Known major publishers (for AAA classification)
AAA_PUBLISHERS = {
    "capcom", "electronic arts", "ea", "ubisoft", "activision", "blizzard",
    "square enix", "bandai namco", "konami", "sega", "2k games", "take-two",
    "bethesda", "rockstar games", "sony", "playstation", "microsoft",
    "xbox game studios", "warner bros", "wb games", "thq nordic",
    "deep silver", "focus entertainment", "remedy entertainment",
    "bloober team", "supermassive games", "techland", "krafton",
    "striking distance", "ea motive", "motive studio",
}

# Steam search cache to avoid duplicate lookups
_search_cache = {}


def search_steam(game_name, retries=3):
    """Search Steam store for a game. Returns app_id or None."""
    clean = game_name.strip()
    if clean in _search_cache:
        return _search_cache[clean]

    # Clean up common suffixes that hurt search
    search_term = clean
    for suffix in [" (Puppet Combo)", " DLC", " Remastered", " Remake",
                   " Deluxe", " Edition", " PS5"]:
        search_term = search_term.replace(suffix, "")
    search_term = search_term.strip()

    for attempt in range(retries):
        try:
            resp = requests.get(
                "https://store.steampowered.com/api/storesearch/",
                params={"term": search_term, "l": "english", "cc": "US"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    # Try exact match first
                    for item in items:
                        if item["name"].lower() == clean.lower():
                            _search_cache[clean] = item["id"]
                            return item["id"]
                    # Try partial match
                    for item in items:
                        if search_term.lower() in item["name"].lower():
                            _search_cache[clean] = item["id"]
                            return item["id"]
                    # Fall back to first result
                    _search_cache[clean] = items[0]["id"]
                    return items[0]["id"]

            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue

        except requests.RequestException:
            time.sleep(1)

    _search_cache[clean] = None
    return None


def get_steam_details(app_id, retries=3):
    """Get full details for a Steam app. Returns dict or None."""
    for attempt in range(retries):
        try:
            resp = requests.get(
                "https://store.steampowered.com/api/appdetails",
                params={"appids": app_id, "cc": "US", "l": "english"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                app_data = data.get(str(app_id), {})
                if app_data.get("success"):
                    return app_data["data"]

            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue

        except requests.RequestException:
            time.sleep(1)

    return None


def get_deck_compat(app_id, retries=2):
    """Check Steam Deck compatibility. Returns status string."""
    for attempt in range(retries):
        try:
            resp = requests.get(
                f"https://store.steampowered.com/saleaction/ajaxgetdeckappcompatibilityreport",
                params={"nAppID": app_id},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", {})
                resolved = results.get("resolved_category", 0)
                # 0 = Unknown, 1 = Unsupported, 2 = Playable, 3 = Verified
                return {0: "Unknown", 1: "Unsupported", 2: "Playable", 3: "Verified"}.get(resolved, "Unknown")
        except requests.RequestException:
            time.sleep(1)
    return "Unknown"


def classify_aaa_indie(details):
    """Classify as AAA, AA, or Indie based on publisher/developer."""
    if not details:
        return "Unknown"

    publishers_raw = details.get("publishers", [])
    developers_raw = details.get("developers", [])
    # Steam returns these as list of strings (not dicts)
    publishers = [p.lower() if isinstance(p, str) else p.get("publisher", "").lower() for p in publishers_raw]
    developers = [d.lower() if isinstance(d, str) else d.get("developer", "").lower() for d in developers_raw]

    # Check publishers first
    for pub in publishers:
        if any(aaa in pub for aaa in AAA_PUBLISHERS):
            return "AAA"

    # Check developers
    for dev in developers:
        if any(aaa in dev for aaa in AAA_PUBLISHERS):
            return "AAA"

    # Heuristic: if price > $40 at launch, likely AA+
    price = details.get("price_overview", {})
    if price:
        initial = price.get("initial", 0) / 100
        if initial >= 50:
            return "AAA"
        elif initial >= 25:
            return "AA"

    return "Indie"


def extract_genres(details):
    """Extract genre names from Steam details."""
    if not details:
        return ""
    genres = details.get("genres", [])
    return ", ".join(g.get("description", "") for g in genres)


def extract_categories(details):
    """Extract category names (multiplayer, co-op, etc.)."""
    if not details:
        return ""
    cats = details.get("categories", [])
    return ", ".join(c.get("description", "") for c in cats)


def get_review_summary(details):
    """Get review summary text."""
    if not details:
        return ""
    recs = details.get("recommendations", {})
    total = recs.get("total", 0)
    if total == 0:
        return "No reviews"
    return f"{total:,} reviews"


# ---------------------------------------------------------------------------
# Dedup / merge logic (same as in the markdown generator)
# ---------------------------------------------------------------------------

MERGE_MAP = {
    "THE LAST OF US 2 PS5": "The Last of Us 2",
    "THE LAST OF 2 PS5": "The Last of Us 2",
    "The Last of us 2 Remastered": "The Last of Us 2",
    "DYING LIGHT 2": "Dying Light 2",
    "Dying Light 2025": "Dying Light",
    "I Finished Dying Light 2025": "Dying Light",
    "Dying Light:The Beast Early": "Dying Light The Beast",
    "DEAD SPACE REMAKE NEW GAMEPLAY": "Dead Space Remake",
    "CRONOS THE NEW DAWN": "Cronos The New Dawn",
    "Outlast. LIVE": "Outlast",
    "Until Dawn PS5": "Until Dawn",
    "Resident Evil Requiem & Silent Hill f Reaction": "Resident Evil Requiem",
    "I Finally Played Resident Evil 6 After Requiem": "Resident Evil 6",
    "Resident Evil 4 Remake Ending is Gaming Perfection": "Resident Evil 4 Remake",
    "I Forgot How Incredible Resident Evil 4 Remake Was": "Resident Evil 4 Remake",
    "I Finally Played Five Nights at Freddys and I MAY NEVER RECOVER": "Five Nights at Freddy's",
    "Little Nightmares 3 Had Me Stressed Out": "Little Nightmares 3",
    "Still Wakes The Deep: Sirens Rest": "Still Wakes The Deep",
    "Puppet Combo's Skinfreak": "SkinFREAK (Puppet Combo)",
    "Puppet Combo's New TAXI SIMULATOR HORROR GAME IS PEAK": "SkinFREAK (Puppet Combo)",
    "The Power Drill Massacre is Actually TERRIFYING": "Power Drill Massacre",
    "Surviving Siren Head in the Woods": "Siren Head",
    "ALONE IN THE FOREST": "Alone in the Forest",
    "TAKEN": "Taken",
    "ROUTINE": "Routine",
}


def deduplicate_games(data):
    """Merge duplicate game entries and return sorted list."""
    merged = defaultdict(lambda: {"videos": [], "count": 0})
    for g in data["games"]:
        title = MERGE_MAP.get(g["title"], g["title"])
        merged[title]["videos"].extend(g["videos"])
        merged[title]["count"] += g["video_count"]
    return sorted(merged.items(), key=lambda x: x[1]["count"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build horror games spreadsheet with Steam data")
    parser.add_argument("--input", default="horror_games_data.json", help="Input JSON file")
    parser.add_argument("--output", default="horror_games.csv", help="Output CSV file")
    parser.add_argument("--skip-steam", action="store_true", help="Skip Steam lookups (faster)")
    parser.add_argument("--limit", type=int, help="Only process first N games (for testing)")
    args = parser.parse_args()

    print("=" * 60)
    print("  HollowPoiint Horror Games Spreadsheet Builder")
    print("=" * 60)

    with open(args.input) as f:
        data = json.load(f)

    sorted_games = deduplicate_games(data)
    if args.limit:
        sorted_games = sorted_games[:args.limit]

    print(f"\nProcessing {len(sorted_games)} unique games...")
    if not args.skip_steam:
        print("Looking up each game on Steam (this will take a few minutes)...\n")

    rows = []
    steam_found = 0
    steam_missed = 0

    for i, (title, info) in enumerate(sorted_games):
        row = {
            "Game Title": title,
            "HollowPoiint Videos": info["count"],
            "Sample Video URL": info["videos"][0]["url"] if info["videos"] else "",
            "Sample Video Title": info["videos"][0]["title"] if info["videos"] else "",
            "Steam URL": "",
            "Steam App ID": "",
            "Price (USD)": "",
            "Genres": "",
            "Categories": "",
            "Developer": "",
            "Publisher": "",
            "AAA / Indie": "",
            "Steam Deck": "",
            "Release Date": "",
            "Review Count": "",
            "Metacritic": "",
            "Short Description": "",
            "Platforms": "",
        }

        if not args.skip_steam:
            # Search Steam
            app_id = search_steam(title)

            if app_id:
                row["Steam App ID"] = app_id
                row["Steam URL"] = f"https://store.steampowered.com/app/{app_id}"

                # Get details
                details = get_steam_details(app_id)
                if details:
                    row["Genres"] = extract_genres(details)
                    row["Categories"] = extract_categories(details)

                    devs = details.get("developers", [])
                    row["Developer"] = ", ".join(devs) if devs else ""

                    pubs = details.get("publishers", [])
                    row["Publisher"] = ", ".join(pubs) if pubs else ""

                    row["AAA / Indie"] = classify_aaa_indie(details)

                    price = details.get("price_overview", {})
                    if price:
                        row["Price (USD)"] = f"${price.get('initial', 0) / 100:.2f}"
                    elif details.get("is_free"):
                        row["Price (USD)"] = "Free"

                    row["Release Date"] = details.get("release_date", {}).get("date", "")
                    row["Review Count"] = get_review_summary(details)

                    meta = details.get("metacritic", {})
                    if meta:
                        row["Metacritic"] = str(meta.get("score", ""))

                    row["Short Description"] = details.get("short_description", "")[:200]

                    # Platforms
                    platforms = details.get("platforms", {})
                    plats = []
                    if platforms.get("windows"): plats.append("Windows")
                    if platforms.get("mac"): plats.append("Mac")
                    if platforms.get("linux"): plats.append("Linux")
                    row["Platforms"] = ", ".join(plats)

                # Steam Deck compat
                deck = get_deck_compat(app_id)
                row["Steam Deck"] = deck
                steam_found += 1
            else:
                steam_missed += 1

            # Progress
            if (i + 1) % 10 == 0:
                print(f"  [{i+1}/{len(sorted_games)}] Processed... "
                      f"(Steam: {steam_found} found, {steam_missed} missed)")

            # Rate limit: Steam API is generous but let's be polite
            time.sleep(0.3)

        rows.append(row)

    # Write CSV
    if rows:
        fieldnames = list(rows[0].keys())
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    print(f"\n{'=' * 60}")
    print(f"Spreadsheet saved: {args.output}")
    print(f"  Total games: {len(rows)}")
    if not args.skip_steam:
        print(f"  Steam matches: {steam_found}")
        print(f"  Steam misses: {steam_missed}")
    print(f"{'=' * 60}")
    print(f"\nOpen in Excel/Google Sheets: {args.output}")


if __name__ == "__main__":
    main()
