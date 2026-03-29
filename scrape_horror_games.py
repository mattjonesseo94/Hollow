#!/usr/bin/env python3
"""
Scrape HollowPoiint's YouTube channel for horror game videos.

Two methods available:
  1. scrapetube (no API key needed, but may be blocked in some environments)
  2. YouTube Data API v3 (requires a free API key from Google Cloud Console)

Usage:
  # Method 1: scrapetube (default, no setup needed)
  python3 scrape_horror_games.py

  # Method 2: YouTube Data API (more reliable, needs API key)
  python3 scrape_horror_games.py --api-key YOUR_API_KEY

  # Get a free API key:
  #   1. Go to https://console.cloud.google.com/
  #   2. Create a project (or use existing)
  #   3. Enable "YouTube Data API v3"
  #   4. Create credentials -> API key
  #   5. Free tier: 10,000 quota units/day (~100 list requests)

Output:
  - horror_games_data.json    (full structured data)
  - horror_games_report.md    (readable markdown report)
"""

import argparse
import json
import re
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Horror keyword detection
# ---------------------------------------------------------------------------

HORROR_KEYWORDS = [
    # Genre terms
    "horror", "scary", "terrifying", "creepy", "haunted", "nightmare",
    "jump scare", "jumpscare", "frightening", "spooky", "disturbing",
    "demon", "paranormal", "possessed", "exorcis",
    # Confirmed games (from research)
    "madison", "reveil", "outlast", "resident evil", "biohazard",
    "silent hill", "dead space", "amnesia", "until dawn", "visage",
    "phasmophobia", "poppy playtime", "fnaf", "five nights at freddy",
    "bendy and the ink machine", "granny", "little nightmares",
    "the evil within", "evil within", "alien isolation", "alien: isolation",
    "the forest", "sons of the forest", "the quarry", "layers of fear",
    "blair witch", "alan wake", "callisto protocol", "scorn",
    "lethal company", "devour", "dark pictures", "man of medan",
    "house of ashes", "devil in me", "tormented souls", "martha is dead",
    "in sound mind", "observer", "maid of sker", "soma", "iron lung",
    "fears to fathom", "at dead of night", "dagon", "paranormal activity",
    "dying light", "the last of us", "dead by daylight",
    "walking dead", "zombie", "zombies",
    "the medium", "the mortuary assistant", "mortuary assistant",
    "puppet combo", "chilla's art", "chillas art",
    "backrooms", "slender", "scp",
    "signalis", "fatal frame", "dredge",
    "the texas chain saw", "texas chainsaw",
    "dead island", "condemned", "cry of fear",
    "penumbra", "detention", "devotion", "mundaun",
    "infliction", "luto", "the bridge curse",
    "content warning", "darkwood",
    "tattletail", "dark deception", "choo-choo charles", "choo choo charles",
    "nun massacre", "bloodwash", "trenches", "amanda the adventurer",
    "silver chains", "crimson snow", "scrutinized", "beast inside",
    "do you copy", "home sweet home", "amenti",
    "from the darkness", "dead rising", "skinfreak",
    "wolf among us", "still wakes the deep",
    "case records", "fear of abduction",
    "re7", "re8", "re4", "re2",
]

HORROR_PATTERN = re.compile(
    "|".join(re.escape(k) for k in HORROR_KEYWORDS),
    re.IGNORECASE,
)


def find_horror_keywords(text: str) -> list[str]:
    """Return deduplicated list of horror keywords found in text."""
    return list(set(HORROR_PATTERN.findall(text.lower())))


def extract_game_name(title: str) -> str:
    """Best-effort extraction of game name from a video title."""
    game = title
    # Common separators between game name and episode/part info
    for sep in [" - ", " | ", " Part ", " part ", " Ep.", " Ep ",
                " Episode ", " episode ", " Walkthrough", " walkthrough",
                " Gameplay", " gameplay", " Full Game", " FULL GAME",
                " Full Playthrough", " FULL PLAYTHROUGH",
                " Chapter ", " chapter ", " #", " (FULL", " (Full"]:
        if sep in game:
            game = game.split(sep)[0]
    # Remove trailing punctuation
    game = game.strip().rstrip(".-!|:")
    return game.strip()


# ---------------------------------------------------------------------------
# Method 1: scrapetube
# ---------------------------------------------------------------------------

def scrape_with_scrapetube(channel_url: str) -> list[dict]:
    """Scrape all videos using scrapetube (no API key needed)."""
    try:
        import scrapetube
    except ImportError:
        print("Installing scrapetube...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "scrapetube", "-q"])
        import scrapetube

    print(f"Fetching videos from {channel_url} via scrapetube...")
    print("(This may take several minutes for 6,000+ videos)\n")

    videos = []
    for i, raw in enumerate(scrapetube.get_channel(channel_url=channel_url)):
        vid_id = raw.get("videoId", "")

        # Extract title
        title = raw.get("title", {})
        if isinstance(title, dict):
            title = title.get("runs", [{}])[0].get("text", "")
        elif isinstance(title, list):
            title = title[0].get("text", "") if title else ""
        else:
            title = str(title)

        # Duration
        dur = raw.get("lengthText", {})
        duration = dur.get("simpleText", "") if isinstance(dur, dict) else str(dur)

        # Views
        vc = raw.get("viewCountText", {})
        views = vc.get("simpleText", "") if isinstance(vc, dict) else str(vc)

        # Published
        pt = raw.get("publishedTimeText", {})
        published = pt.get("simpleText", "") if isinstance(pt, dict) else str(pt)

        # Description snippet
        desc = raw.get("descriptionSnippet", {})
        if isinstance(desc, dict):
            description = " ".join(r.get("text", "") for r in desc.get("runs", []))
        else:
            description = ""

        videos.append({
            "id": vid_id,
            "title": title,
            "url": f"https://youtube.com/watch?v={vid_id}",
            "duration": duration,
            "views": views,
            "published": published,
            "description": description,
        })

        if (i + 1) % 500 == 0:
            print(f"  ...scanned {i + 1} videos")

    return videos


# ---------------------------------------------------------------------------
# Method 2: YouTube Data API v3
# ---------------------------------------------------------------------------

def scrape_with_api(api_key: str, channel_handle: str = "hollowpoiint") -> list[dict]:
    """Scrape all videos using YouTube Data API v3."""
    import requests

    BASE = "https://www.googleapis.com/youtube/v3"

    # Step 1: Resolve channel handle to channel ID
    print(f"Resolving @{channel_handle}...")
    resp = requests.get(f"{BASE}/channels", params={
        "forHandle": channel_handle,
        "part": "contentDetails,snippet",
        "key": api_key,
    })
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        # Try search fallback
        resp = requests.get(f"{BASE}/search", params={
            "q": channel_handle,
            "type": "channel",
            "part": "snippet",
            "maxResults": 1,
            "key": api_key,
        })
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            print("ERROR: Could not find channel. Check the handle.")
            sys.exit(1)
        channel_id = items[0]["snippet"]["channelId"]
    else:
        channel_id = items[0]["id"]

    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    channel_title = items[0]["snippet"]["title"]
    print(f"Found: {channel_title} ({channel_id})")
    print(f"Uploads playlist: {uploads_playlist}\n")

    # Step 2: Paginate through all uploads
    videos = []
    next_page = None
    page = 0

    while True:
        page += 1
        params = {
            "playlistId": uploads_playlist,
            "part": "snippet,contentDetails",
            "maxResults": 50,
            "key": api_key,
        }
        if next_page:
            params["pageToken"] = next_page

        resp = requests.get(f"{BASE}/playlistItems", params=params)
        if resp.status_code == 403:
            print(f"\nAPI quota exceeded after {len(videos)} videos.")
            print("You can re-run tomorrow (quota resets at midnight PT)")
            print("or increase your quota in Google Cloud Console.\n")
            break
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            snippet = item["snippet"]
            vid_id = snippet["resourceId"]["videoId"]
            videos.append({
                "id": vid_id,
                "title": snippet.get("title", ""),
                "url": f"https://youtube.com/watch?v={vid_id}",
                "duration": "",  # Would need separate videos.list call
                "views": "",
                "published": snippet.get("publishedAt", ""),
                "description": snippet.get("description", "")[:300],
            })

        print(f"  Page {page}: fetched {len(data.get('items', []))} videos "
              f"(total: {len(videos)})")

        next_page = data.get("nextPageToken")
        if not next_page:
            break

    return videos


# ---------------------------------------------------------------------------
# Analysis & output
# ---------------------------------------------------------------------------

def analyze_and_output(videos: list[dict]):
    """Filter for horror content, analyze, and write output files."""
    horror_videos = []
    games = defaultdict(list)

    for vid in videos:
        text = f"{vid['title']} {vid.get('description', '')}"
        keywords = find_horror_keywords(text)
        if keywords:
            vid["horror_keywords"] = keywords
            horror_videos.append(vid)
            game = extract_game_name(vid["title"])
            games[game].append(vid)

    # Sort by video count descending
    sorted_games = sorted(games.items(), key=lambda x: len(x[1]), reverse=True)

    # Console summary
    print("\n" + "=" * 60)
    print(f"RESULTS: {len(horror_videos)} horror videos found "
          f"across {len(sorted_games)} unique titles")
    print(f"(out of {len(videos)} total videos scanned)")
    print("=" * 60)

    for game, vids in sorted_games[:30]:
        print(f"\n  {game} ({len(vids)} video{'s' if len(vids) != 1 else ''})")
        print(f"    Keywords: {', '.join(vids[0]['horror_keywords'])}")
        print(f"    Link: {vids[0]['url']}")

    if len(sorted_games) > 30:
        print(f"\n  ... and {len(sorted_games) - 30} more titles")

    # Save JSON
    output = {
        "channel": "https://www.youtube.com/@hollowpoiint",
        "total_videos_scanned": len(videos),
        "horror_videos_found": len(horror_videos),
        "unique_game_titles": len(sorted_games),
        "games": [
            {"title": g, "video_count": len(v), "videos": v}
            for g, v in sorted_games
        ],
    }
    with open("horror_games_data.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Generate markdown report (separate from the main curated list)
    major = [(g, v) for g, v in sorted_games if len(v) >= 3]
    multi = [(g, v) for g, v in sorted_games if len(v) == 2]
    single = [(g, v) for g, v in sorted_games if len(v) == 1]

    with open("horror_games_report.md", "w") as f:
        f.write("# HollowPoiint Horror Games - Scraped Data\n\n")
        f.write(f"**Total Videos Scanned**: {len(videos)}\n")
        f.write(f"**Horror Videos Found**: {len(horror_videos)}\n")
        f.write(f"**Unique Game Titles**: {len(sorted_games)}\n\n")
        f.write("*Auto-generated by `scrape_horror_games.py`*\n\n---\n\n")

        def write_section(title, items):
            if not items:
                return
            f.write(f"## {title}\n\n")
            for i, (game, vids) in enumerate(items, 1):
                kws = sorted(set(kw for v in vids for kw in v.get("horror_keywords", [])))
                f.write(f"{i}. **{game}** ({len(vids)} video{'s' if len(vids) != 1 else ''})\n")
                f.write(f"   - Keywords: {', '.join(kws)}\n")
                f.write(f"   - Latest: [{vids[0]['title']}]({vids[0]['url']})\n")
                if vids[0].get("views"):
                    f.write(f"   - Views: {vids[0]['views']}\n")
                f.write("\n")

        write_section("Full Playthroughs / Major Series (3+ videos)", major)
        write_section("Multi-Part Content (2 videos)", multi)
        write_section("Single Videos", single)

        f.write("---\n\n")
        f.write("## Notes\n\n")
        f.write("- Game titles are best-effort extracted from video titles\n")
        f.write("- Some entries may be duplicates with slightly different naming\n")
        f.write("- Some games have horror elements but aren't strictly horror\n")
        f.write("- Keyword matching may miss videos that don't mention horror "
                "terms in the title/description\n")

    print(f"\n\nFiles saved:")
    print(f"  horror_games_data.json   ({len(horror_videos)} videos, full metadata)")
    print(f"  horror_games_report.md   (readable report)")
    print("\nDone!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape HollowPoiint's YouTube channel for horror game videos"
    )
    parser.add_argument(
        "--api-key",
        help="YouTube Data API v3 key (recommended; get one free at "
             "https://console.cloud.google.com/)",
    )
    parser.add_argument(
        "--channel",
        default="https://www.youtube.com/@hollowpoiint",
        help="Channel URL (default: HollowPoiint)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  HollowPoiint Horror Games Scraper")
    print("=" * 60)

    if args.api_key:
        print("\nUsing YouTube Data API v3")
        videos = scrape_with_api(args.api_key)
    else:
        print("\nUsing scrapetube (no API key)")
        print("Tip: For more reliable results, use --api-key YOUR_KEY")
        videos = scrape_with_scrapetube(args.channel)

    if not videos:
        print("No videos found. Check your connection or API key.")
        sys.exit(1)

    analyze_and_output(videos)


if __name__ == "__main__":
    main()
