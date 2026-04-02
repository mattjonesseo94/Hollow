#!/usr/bin/env python3
"""
HollowPoiint Horror Games Scraper - Deep Analysis Pipeline

3-layer detection:
  Layer 1: Title/description keyword matching (fast, free)
  Layer 2: YouTube auto-captions analysis (medium, free via yt-dlp)
  Layer 3: AI classification via Claude API (slow, paid - optional)

Requirements:
  pip install scrapetube yt-dlp anthropic

Usage:
  # Layer 1 only (keyword matching on titles/descriptions)
  python3 scrape_horror_games.py

  # Layer 1 + 2 (also pull captions for ambiguous videos)
  python3 scrape_horror_games.py --deep

  # Layer 1 + 2 + 3 (also use Claude AI to classify unknowns)
  python3 scrape_horror_games.py --deep --anthropic-key sk-ant-...

  # Use YouTube Data API instead of scrapetube
  python3 scrape_horror_games.py --deep --yt-api-key YOUR_KEY
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Horror keyword detection (Layer 1)
# ---------------------------------------------------------------------------

HORROR_KEYWORDS = [
    # Genre terms
    "horror", "scary", "terrifying", "creepy", "haunted", "nightmare",
    "jump scare", "jumpscare", "frightening", "spooky", "disturbing",
    "demon", "paranormal", "possessed", "exorcis",
    # Confirmed HollowPoiint horror games
    "madison", "reveil", "outlast", "resident evil", "biohazard",
    "silent hill", "dead space", "amnesia", "until dawn", "visage",
    "phasmophobia", "poppy playtime", "fnaf", "five nights at freddy",
    "bendy and the ink machine", "granny", "little nightmares",
    "the evil within", "evil within", "alien isolation",
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
    "texas chain saw", "texas chainsaw",
    "dead island", "condemned", "cry of fear",
    "penumbra", "detention", "devotion", "mundaun",
    "infliction", "luto", "the bridge curse",
    "content warning", "darkwood",
    "tattletail", "dark deception", "choo-choo charles",
    "nun massacre", "bloodwash", "trenches", "amanda the adventurer",
    "silver chains", "crimson snow", "scrutinized", "beast inside",
    "do you copy", "home sweet home", "amenti",
    "from the darkness", "dead rising", "skinfreak",
    "wolf among us", "still wakes the deep",
    "case records", "fear of abduction",
    "re7", "re8", "re4", "re2",
    "hellmart", "unreal pt",
]

HORROR_PATTERN = re.compile(
    "|".join(re.escape(k) for k in HORROR_KEYWORDS),
    re.IGNORECASE,
)

# Titles that suggest horror but don't name the game
CLICKBAIT_PATTERNS = [
    r"never playing this",
    r"scariest game",
    r"don'?t play this",
    r"this game broke me",
    r"i couldn'?t finish",
    r"most terrifying",
    r"i regret playing",
    r"this game is cursed",
    r"scared me",
    r"can'?t sleep",
    r"nightmare fuel",
    r"night shift",
    r"nightshift",
    r"working late",
    r"working the",
    r"overnight at",
    r"i rented a cabin",
    r"cabin in the woods",
    r"abandoned",
    r"i took a .* job",
    r"followed me home",
    r"not human",
    r"aren'?t human",
    r"home invasion",
    r"missing .* case",
    r"serial killer",
    r"stalker",
    r"stalked",
    r"im being stalked",
    r"shouldn'?t have stayed",
    r"was a mistake",
    r"hyper.?realistic horror",
    r"body.?cam horror",
    r"bodycam horror",
    r"vhs horror",
    r"pt inspired",
    r"jumpscares",
    r"diabolical",
    r"uncomfortable",
    r"disturbing",
    r"demonic",
    r"this .* destroyed me",
    r"blew my mind",
    r"chokehold",
    r"sleep paralysis",
    r"park ranger",
    r"went wrong",
    r"gone wrong",
    r"something is wrong",
    r"new fear",
    r"unlocked a .* fear",
    r"i'?m exhausted",
    r"i'?m done",
    r"im done",
    r"enough horror",
    r"can'?t take it",
    r"i cant take",
    r"the customers",
    r"paranormal",
    r"ghost hunt",
    r"haunted",
    r"a horror game",
    r"this horror",
    r"new horror",
    r"indie horror",
    r"japanese horror",
    r"chinese horror",
    r"korean horror",
    r"filipino horror",
    r"based on true",
    r"true events",
    r"true story",
    r"cold case",
    r"missing hikers",
    r"missing person",
    r"disappearing",
    r"lighthouse",
    r"motel",
    r"cemetery",
    r"morgue",
    r"mortuary",
    r"asylum",
    r"escape the",
    r"trapped in",
    r"i played a",
    r"finally played",
]
CLICKBAIT_RE = re.compile("|".join(CLICKBAIT_PATTERNS), re.IGNORECASE)


def find_horror_keywords(text):
    return list(set(HORROR_PATTERN.findall(text.lower())))


def is_clickbait_horror(title):
    return bool(CLICKBAIT_RE.search(title))


def extract_game_name(title):
    game = title
    for sep in [" - ", " | ", " Part ", " part ", " Ep.", " Ep ",
                " Episode ", " episode ", " Walkthrough", " walkthrough",
                " Gameplay", " gameplay", " Full Game", " FULL GAME",
                " Full Playthrough", " FULL PLAYTHROUGH",
                " Chapter ", " chapter ", " #", " (FULL", " (Full"]:
        if sep in game:
            game = game.split(sep)[0]
    return game.strip().rstrip(".-!|:")


# ---------------------------------------------------------------------------
# Layer 2: Caption/subtitle extraction via yt-dlp
# ---------------------------------------------------------------------------

def fetch_captions(video_id, cache_dir="caption_cache"):
    """Download auto-generated captions for a video. Returns text or None."""
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = Path(cache_dir) / f"{video_id}.txt"

    if cache_file.exists():
        return cache_file.read_text()

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--write-auto-sub",
                "--sub-lang", "en",
                "--sub-format", "vtt",
                "--output", str(Path(cache_dir) / "%(id)s"),
                f"https://youtube.com/watch?v={video_id}",
            ],
            capture_output=True, text=True, timeout=30,
        )

        vtt_file = Path(cache_dir) / f"{video_id}.en.vtt"
        if vtt_file.exists():
            raw = vtt_file.read_text()
            # Strip VTT formatting, keep just the text
            lines = []
            for line in raw.split("\n"):
                line = line.strip()
                if not line or line.startswith("WEBVTT") or "-->" in line:
                    continue
                if line.startswith("<"):
                    continue
                # Remove VTT tags
                clean = re.sub(r"<[^>]+>", "", line)
                if clean and clean not in lines[-1:]:
                    lines.append(clean)
            text = " ".join(lines)
            cache_file.write_text(text)
            vtt_file.unlink()
            return text
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Write empty cache to avoid re-trying
    cache_file.write_text("")
    return None


def analyze_captions_for_game(captions, title):
    """Search captions for game name mentions. Returns best guess or None."""
    if not captions:
        return None

    # Check first ~3 mins of captions (where YouTubers usually name the game)
    intro = captions[:3000]
    full = captions[:8000]

    # Patterns where YouTubers explicitly name the game
    intro_patterns = [
        # Direct naming
        r"(?:welcome back to|playing|let'?s play|this is|today we(?:'re| are) playing|we(?:'re| are) playing|jumping into|diving into|checking out|trying out|starting)\s+([A-Z][A-Za-z0-9:' \-\.]{2,40})",
        r"(?:this game is called|the game is called|the game is|this game is|it'?s called)\s+([A-Z][A-Za-z0-9:' \-\.]{2,40})",
        r"(?:we got|i got|playing some|back with|back to|return to|returning to|continuing)\s+([A-Z][A-Za-z0-9:' \-\.]{2,40})",
        # Description link mentions
        r"(?:link to|download|steam page|get the game|wishlist)\s+([A-Z][A-Za-z0-9:' \-\.]{2,40})",
    ]

    candidates = []
    for pattern in intro_patterns:
        for match in re.finditer(pattern, intro):
            game = match.group(1).strip().rstrip(".,!?;:")
            # Filter out common false positives
            skip_words = {"this", "the", "that", "a", "an", "my", "our", "your",
                          "it", "so", "one", "some", "something", "guys",
                          "man", "bro", "what", "yeah", "okay", "alright",
                          "welcome", "back", "here", "today", "now",
                          "episode", "part", "chapter"}
            if len(game) > 3 and game.split()[0].lower() not in skip_words:
                candidates.append(game)

    # Also scan for known horror game names in full captions
    known_games_in_captions = find_horror_keywords(full)
    if known_games_in_captions:
        # Return the most specific keyword match
        longest = max(known_games_in_captions, key=len)
        return longest.title()

    # Return first candidate if we found any
    if candidates:
        return candidates[0]

    return None


def analyze_captions_deep(captions, title):
    """Deeper caption analysis: check for horror themes even without game name."""
    if not captions:
        return False, []

    text = captions[:10000].lower()

    # Horror atmosphere indicators in speech
    horror_speech = [
        "scared", "terrified", "oh my god", "what the", "jump scare",
        "don't look", "behind you", "run run run", "no no no",
        "i'm dead", "it's coming", "monster", "creature", "ghost",
        "demon", "blood", "screaming", "help me", "get out",
        "basement", "dark", "flashlight", "hide", "hiding",
        "heartbeat", "breathing", "footsteps", "door locked",
        "killed me", "she's coming", "he's coming", "it's here",
        "ritual", "sacrifice", "possessed", "cursed", "haunted",
        "nightmare", "asylum", "morgue", "cemetery", "grave",
    ]

    matches = [w for w in horror_speech if w in text]
    # If 5+ horror speech indicators, it's likely horror
    is_horror = len(matches) >= 5
    return is_horror, matches


# ---------------------------------------------------------------------------
# Layer 3: AI classification via Claude API
# ---------------------------------------------------------------------------

def classify_with_claude(video_info, captions_snippet, api_key):
    """Use Claude to identify the game and classify horror content."""
    try:
        import anthropic
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "anthropic", "-q"])
        import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    game_hint = video_info.get("caption_game_guess", "")
    hint_line = f"\nPossible game name from captions: {game_hint}" if game_hint else ""

    prompt = f"""Analyze this YouTube gaming video from HollowPoiint's channel and identify:
1. The exact video game being played (full official title)
2. Whether it's a horror game (yes/no/partial - "partial" means horror elements but not primarily horror)
3. The horror subgenre if applicable (e.g. survival horror, psychological horror, indie horror, co-op horror, etc.)

Video title: {video_info['title']}
Video description: {video_info.get('description', 'N/A')}{hint_line}
Caption excerpt (first 2000 chars): {(captions_snippet or 'No captions available')[:2000]}

Respond ONLY with valid JSON, no other text:
{{"game_title": "...", "is_horror": true/false, "horror_type": "...", "confidence": "high/medium/low"}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        # Extract JSON from response
        json_match = re.search(r"\{[^}]+\}", text)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"    Claude API error: {e}")

    return None


# ---------------------------------------------------------------------------
# Video fetching (scrapetube or YouTube API)
# ---------------------------------------------------------------------------

def scrape_with_scrapetube(channel_url):
    try:
        import scrapetube
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "scrapetube", "-q"])
        import scrapetube

    print(f"Fetching videos from {channel_url} via scrapetube...")
    print("(This may take several minutes for 6,000+ videos)\n")

    videos = []
    for i, raw in enumerate(scrapetube.get_channel(channel_url=channel_url)):
        vid_id = raw.get("videoId", "")
        title = raw.get("title", {})
        if isinstance(title, dict):
            title = title.get("runs", [{}])[0].get("text", "")
        elif isinstance(title, list):
            title = title[0].get("text", "") if title else ""
        else:
            title = str(title)

        dur = raw.get("lengthText", {})
        duration = dur.get("simpleText", "") if isinstance(dur, dict) else str(dur)
        vc = raw.get("viewCountText", {})
        views = vc.get("simpleText", "") if isinstance(vc, dict) else str(vc)
        pt = raw.get("publishedTimeText", {})
        published = pt.get("simpleText", "") if isinstance(pt, dict) else str(pt)
        desc = raw.get("descriptionSnippet", {})
        description = ""
        if isinstance(desc, dict):
            description = " ".join(r.get("text", "") for r in desc.get("runs", []))

        videos.append({
            "id": vid_id, "title": title,
            "url": f"https://youtube.com/watch?v={vid_id}",
            "duration": duration, "views": views,
            "published": published, "description": description,
        })
        if (i + 1) % 500 == 0:
            print(f"  ...scanned {i + 1} videos")

    return videos


def scrape_with_api(api_key, channel_handle="hollowpoiint"):
    import requests
    BASE = "https://www.googleapis.com/youtube/v3"

    print(f"Resolving @{channel_handle}...")
    resp = requests.get(f"{BASE}/channels", params={
        "forHandle": channel_handle, "part": "contentDetails,snippet", "key": api_key,
    })
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        print("ERROR: Could not find channel.")
        sys.exit(1)

    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"Found: {items[0]['snippet']['title']}")
    print(f"Uploads playlist: {uploads_playlist}\n")

    videos = []
    next_page = None
    while True:
        params = {
            "playlistId": uploads_playlist, "part": "snippet,contentDetails",
            "maxResults": 50, "key": api_key,
        }
        if next_page:
            params["pageToken"] = next_page
        resp = requests.get(f"{BASE}/playlistItems", params=params)
        if resp.status_code == 403:
            print(f"\nQuota exceeded after {len(videos)} videos. Re-run tomorrow.")
            break
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []):
            s = item["snippet"]
            vid_id = s["resourceId"]["videoId"]
            videos.append({
                "id": vid_id, "title": s.get("title", ""),
                "url": f"https://youtube.com/watch?v={vid_id}",
                "duration": "", "views": "",
                "published": s.get("publishedAt", ""),
                "description": s.get("description", "")[:500],
            })
        print(f"  Fetched {len(videos)} videos...")
        next_page = data.get("nextPageToken")
        if not next_page:
            break

    return videos


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HollowPoiint Horror Games Scraper")
    parser.add_argument("--yt-api-key", help="YouTube Data API v3 key")
    parser.add_argument("--anthropic-key", help="Anthropic API key for Layer 3 AI classification")
    parser.add_argument("--deep", action="store_true",
                        help="Enable Layer 2: pull captions for clickbait-titled videos via yt-dlp")
    parser.add_argument("--deep-all", action="store_true",
                        help="Layer 2 on ALL non-horror videos (slow but catches everything)")
    parser.add_argument("--channel", default="https://www.youtube.com/@hollowpoiint")
    parser.add_argument("--resume", help="Resume from a previous horror_games_data.json")
    args = parser.parse_args()

    print("=" * 60)
    print("  HollowPoiint Horror Games Scraper")
    print("  Layer 1: Keyword matching (title + description)")
    if args.deep or args.deep_all:
        print("  Layer 2: Caption analysis (yt-dlp auto-subs)")
        if args.deep_all:
            print("           (scanning ALL videos, not just clickbait)")
    if args.anthropic_key:
        print("  Layer 3: AI classification (Claude Haiku)")
    print("=" * 60)

    # --- Fetch or resume ---
    if args.resume and Path(args.resume).exists():
        print(f"\nResuming from {args.resume}...")
        with open(args.resume) as f:
            prev = json.load(f)
        all_videos = []
        for g in prev.get("games", []):
            all_videos.extend(g.get("videos", []))
        # Also need non-horror videos for deep analysis
        print(f"  Loaded {len(all_videos)} previously identified horror videos")
        videos = all_videos
    else:
        if args.yt_api_key:
            videos = scrape_with_api(args.yt_api_key)
        else:
            videos = scrape_with_scrapetube(args.channel)

    if not videos:
        print("No videos found.")
        sys.exit(1)

    print(f"\nTotal videos: {len(videos)}")

    # --- Layer 1: Keyword matching ---
    print("\n--- Layer 1: Keyword matching ---")
    horror_videos = []
    maybe_horror = []  # Clickbait titles that might be horror
    non_horror = []

    for vid in videos:
        text = f"{vid['title']} {vid.get('description', '')}"
        kws = find_horror_keywords(text)
        if kws:
            vid["horror_keywords"] = kws
            vid["detection"] = "layer1_keywords"
            horror_videos.append(vid)
        elif is_clickbait_horror(vid["title"]):
            vid["detection"] = "layer2_candidate"
            maybe_horror.append(vid)
        else:
            non_horror.append(vid)

    print(f"  Confirmed horror (keywords): {len(horror_videos)}")
    print(f"  Possible horror (clickbait titles): {len(maybe_horror)}")
    print(f"  Non-horror: {len(non_horror)}")

    # --- Layer 2: Caption analysis ---
    # --deep-all: also scan non-horror videos for hidden horror content
    if args.deep_all:
        maybe_horror.extend(non_horror)
        print(f"\n  --deep-all: added {len(non_horror)} non-horror videos to scan queue")

    if (args.deep or args.deep_all) and maybe_horror:
        print(f"\n--- Layer 2: Analyzing captions for {len(maybe_horror)} ambiguous videos ---")
        print("  (requires yt-dlp: pip install yt-dlp)\n")

        layer2_confirmed = 0
        layer2_deep = 0
        layer2_nocaps = 0

        for i, vid in enumerate(maybe_horror):
            print(f"  [{i+1}/{len(maybe_horror)}] {vid['title'][:70]}...")
            captions = fetch_captions(vid["id"])

            if captions:
                # Step A: Check captions for horror game keywords
                cap_kws = find_horror_keywords(captions[:5000])
                if cap_kws:
                    vid["horror_keywords"] = cap_kws
                    vid["detection"] = "layer2_captions"
                    horror_videos.append(vid)
                    layer2_confirmed += 1
                    print(f"    -> HORROR (caption keywords: {', '.join(cap_kws[:3])})")
                    continue

                # Step B: Try to extract game name from captions
                game = analyze_captions_for_game(captions, vid["title"])
                if game:
                    vid["caption_game_guess"] = game
                    game_kws = find_horror_keywords(game)
                    if game_kws:
                        vid["horror_keywords"] = game_kws
                        vid["detection"] = "layer2_game_name"
                        horror_videos.append(vid)
                        layer2_confirmed += 1
                        print(f"    -> HORROR (game identified: {game})")
                        continue
                    else:
                        # We found a game name but couldn't confirm it's horror
                        vid["caption_game_guess"] = game
                        vid["detection"] = "layer2_game_found_unconfirmed"
                        print(f"    -> Game found: '{game}' (not confirmed horror)")

                # Step C: Deep caption analysis - check for horror atmosphere
                is_horror, speech_matches = analyze_captions_deep(captions, vid["title"])
                if is_horror:
                    vid["horror_keywords"] = speech_matches[:5]
                    vid["detection"] = "layer2_deep_analysis"
                    horror_videos.append(vid)
                    layer2_deep += 1
                    print(f"    -> HORROR (speech analysis: {', '.join(speech_matches[:3])})")
                    continue

                vid["_captions_checked"] = True
                print(f"    -> Not confirmed as horror")
            else:
                layer2_nocaps += 1
                print(f"    -> No captions available")

            # Rate limit to be polite to YouTube
            if (i + 1) % 10 == 0:
                time.sleep(1)

        print(f"\n  Layer 2 results:")
        print(f"    Confirmed by keywords/game name: {layer2_confirmed}")
        print(f"    Confirmed by speech analysis:    {layer2_deep}")
        print(f"    No captions available:           {layer2_nocaps}")
        print(f"    Total horror videos now:         {len(horror_videos)}")

    # --- Layer 3: AI classification ---
    unclassified = [v for v in maybe_horror if v.get("detection") in
                    ("layer2_candidate", "layer2_game_found_unconfirmed")]
    if args.anthropic_key and unclassified:
        print(f"\n--- Layer 3: AI classifying {len(unclassified)} remaining videos ---")
        print("  Using Claude Haiku (fast + cheap)")

        for i, vid in enumerate(unclassified):
            print(f"  [{i+1}/{len(unclassified)}] {vid['title'][:60]}...")

            captions = None
            if args.deep or args.deep_all:
                captions = fetch_captions(vid["id"])

            result = classify_with_claude(vid, captions, args.anthropic_key)
            if result:
                vid["ai_classification"] = result
                if result.get("is_horror"):
                    vid["horror_keywords"] = [result.get("horror_type", "horror")]
                    vid["game_title_ai"] = result.get("game_title", "Unknown")
                    vid["detection"] = "layer3_ai"
                    horror_videos.append(vid)
                    print(f"    -> HORROR: {result.get('game_title')} "
                          f"({result.get('horror_type')}) "
                          f"[{result.get('confidence')}]")
                else:
                    print(f"    -> Not horror ({result.get('game_title', '?')})")
            else:
                print(f"    -> Classification failed")

            # Rate limit
            time.sleep(0.5)

        print(f"\n  After Layer 3: {len(horror_videos)} horror videos confirmed")

    # --- Output ---
    games = defaultdict(list)
    for vid in horror_videos:
        game = vid.get("game_title_ai") or vid.get("caption_game_guess") or extract_game_name(vid["title"])
        vid["_game"] = game
        games[game].append(vid)

    sorted_games = sorted(games.items(), key=lambda x: len(x[1]), reverse=True)

    print("\n" + "=" * 60)
    print(f"FINAL: {len(horror_videos)} horror videos, "
          f"{len(sorted_games)} unique titles")
    print("=" * 60)

    # Detection breakdown
    l1 = sum(1 for v in horror_videos if v.get("detection") == "layer1_keywords")
    l2 = sum(1 for v in horror_videos if v.get("detection", "").startswith("layer2"))
    l3 = sum(1 for v in horror_videos if v.get("detection") == "layer3_ai")
    print(f"\n  Layer 1 (keywords):  {l1} videos")
    if args.deep or args.deep_all:
        print(f"  Layer 2 (captions):  {l2} videos")
    if args.anthropic_key:
        print(f"  Layer 3 (AI):        {l3} videos")

    for game, vids in sorted_games[:40]:
        det = vids[0].get("detection", "?")
        print(f"\n  {game} ({len(vids)} vid{'s' if len(vids)!=1 else ''}) [{det}]")
        print(f"    {vids[0]['url']}")

    if len(sorted_games) > 40:
        print(f"\n  ...and {len(sorted_games) - 40} more")

    # Save JSON
    output = {
        "channel": "https://www.youtube.com/@hollowpoiint",
        "total_videos_scanned": len(videos),
        "horror_videos_found": len(horror_videos),
        "unique_game_titles": len(sorted_games),
        "detection_breakdown": {"layer1_keywords": l1, "layer2_captions": l2, "layer3_ai": l3},
        "games": [
            {"title": g, "video_count": len(v), "videos": v}
            for g, v in sorted_games
        ],
    }
    with open("horror_games_data.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    # Markdown report
    major = [(g, v) for g, v in sorted_games if len(v) >= 3]
    multi = [(g, v) for g, v in sorted_games if len(v) == 2]
    single = [(g, v) for g, v in sorted_games if len(v) == 1]

    with open("horror_games_report.md", "w") as f:
        f.write("# HollowPoiint Horror Games - Scraped Report\n\n")
        f.write(f"**Total Videos Scanned**: {len(videos)}\n")
        f.write(f"**Horror Videos Found**: {len(horror_videos)}\n")
        f.write(f"**Unique Game Titles**: {len(sorted_games)}\n")
        f.write(f"**Detection**: L1={l1} keywords, L2={l2} captions, L3={l3} AI\n\n")
        f.write("*Auto-generated by `scrape_horror_games.py`*\n\n---\n\n")

        def write_section(title, items):
            if not items:
                return
            f.write(f"## {title}\n\n")
            for i, (game, vids) in enumerate(items, 1):
                kws = sorted(set(kw for v in vids for kw in v.get("horror_keywords", [])))
                det = vids[0].get("detection", "unknown")
                f.write(f"{i}. **{game}** ({len(vids)} video{'s' if len(vids)!=1 else ''}) `[{det}]`\n")
                f.write(f"   - Keywords: {', '.join(kws)}\n")
                f.write(f"   - Latest: [{vids[0]['title']}]({vids[0]['url']})\n")
                if vids[0].get("views"):
                    f.write(f"   - Views: {vids[0]['views']}\n")
                f.write("\n")

        write_section("Full Playthroughs / Major Series (3+ videos)", major)
        write_section("Multi-Part Content (2 videos)", multi)
        write_section("Single Videos", single)

    print(f"\nSaved: horror_games_data.json, horror_games_report.md")
    print("Done!")


if __name__ == "__main__":
    main()
