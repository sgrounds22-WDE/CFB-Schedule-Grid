#!/usr/bin/env python3
"""
Build a college football TV grid as a static web page.

  python build.py                    # this Saturday plus the next two
  python build.py --weeks 1          # just the upcoming Saturday
  python build.py --date 2026-09-12  # start from a specific Saturday

Writes public/index.html and public/schedule.json. Everything the page needs is
baked in at build time, so the page makes no network calls of its own and does
not depend on ESPN being reachable from the browser.

Data comes from ESPN's public scoreboard endpoint, which returns kickoff time,
broadcast network, AP rank, conference id and team colors as structured JSON.
"""

import argparse, datetime as dt, json, os, re, sys, urllib.request
from collections import defaultdict

import icons

# ---------------------------------------------------------------- naming
# Change these two and everything follows: browser tab, page heading, the name
# under the home-screen icon, and the app title when launched from it.
APP_NAME  = "CFB TV Schedule"   # full name — page heading, install prompt
APP_SHORT = "CFB TV"            # home screen label; iOS truncates past ~12 chars

# Link previews (Messages, Slack, WhatsApp) need an ABSOLUTE image URL — a
# relative path is ignored and you get the generic browser glyph instead.
SITE_URL  = "https://cfb-schedule-grid.web.app"
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Every kickoff in this script is Eastern. Linux and macOS ship the IANA time
# zone database; Windows does not, so zoneinfo there depends on the `tzdata`
# package. Fail with the fix rather than a bare lookup error.
try:
    ET = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    sys.exit("No time zone database found.\n"
             "On Windows, run:  pip install tzdata")
# ESPN serves the same scoreboard from more than one host. site.api is the
# usual one; site.web.api sometimes answers when the first refuses.
API_HOSTS = [
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
    "/scoreboard?dates={ymd}&groups=80&limit=400",
    "https://site.web.api.espn.com/apis/site/v2/sports/football/college-football"
    "/scoreboard?dates={ymd}&groups=80&limit=400",
]

# ESPN rejects requests that do not look like a browser, which is what a bare
# "cfb-tv-grid/1.0" agent gets you: HTTP 403. These are tried in order and the
# first one that works is reported, so a failure names the fix instead of
# leaving you guessing.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")

HEADER_PROFILES = [
    ("browser+referer", {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.espn.com/college-football/scoreboard",
        "Origin": "https://www.espn.com",
    }),
    ("browser", {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
    }),
    ("plain", {"User-Agent": "cfb-tv-grid/1.0"}),
]

# ESPN conference group ids. Verify these on your first run: the script prints
# any id it does not recognise, along with a team in it, so you can fill gaps.
CONFERENCES = {
    "1": "ACC", "4": "Big 12", "5": "Big Ten", "8": "SEC", "9": "Pac-12",
    "12": "C-USA", "15": "MAC", "17": "Mountain West", "18": "Independent",
    "37": "Sun Belt", "151": "American",
}
CONF_ORDER = ["SEC", "Big Ten", "Big 12", "ACC", "Pac-12", "American",
              "Mountain West", "MAC", "Sun Belt", "C-USA", "Independent", "FCS"]

# Networks that get a row in the grid, in display order. Anything not listed
# here (ESPN+, SECN+, ACCNX, MW+) drops into the streaming list below the grid.
GRID_NETWORKS = ["ABC", "CBS", "FOX", "NBC", "CW", "ESPN", "ESPN2", "ESPNU",
                 "TNT", "FS1", "USA", "PEACOCK", "ACCN", "SECN", "BTN", "CBSSN"]

NETWORK_ALIASES = {
    "ACC Network": "ACCN", "SEC Network": "SECN", "Big Ten Network": "BTN",
    "CBS Sports Network": "CBSSN", "The CW": "CW",
    # ESPN abbreviates USA Network to "USA Net" in the scoreboard feed, which
    # was dropping every USA game into the streaming list.
    "USA Network": "USA", "USA Net": "USA", "USA Net.": "USA",
    "ESPN/Disney+": "ESPN", "ABC/Disney+": "ABC", "TNT/HBO Max": "TNT",
    "TNT/truTV/HBO Max": "TNT", "Peacock": "PEACOCK", "NBC/Peacock": "NBC",
    "FOX/FS1": "FOX", "CBSSN": "CBSSN",
}

STREAM_BADGES = {"ESPN+": "espnplus", "SECN+": "secnplus",
                 "ACCNX": "accnx", "MW+": "mwplus", "ESPN3": "espnplus",
                 "ESPNU+": "espnplus", "Streaming": "espnplus"}

# ESPN's Football Power Index. A different API family from the scoreboard —
# core-v2 rather than site-v2 — but one call covers every team, and the team id
# is embedded in the $ref URL so it needs no follow-up requests.
FPI_URL = ("https://sports.core.api.espn.com/v2/sports/football/leagues/"
           "college-football/seasons/{year}/powerindex?limit=400")

# Matchup Predictor. Unlike FPI this is per game, so it is fetched only for the
# first week by default (see --predict-weeks) to keep request volume sane.
PREDICTOR_URL = ("https://sports.core.api.espn.com/v2/sports/football/leagues/"
                 "college-football/events/{eid}/competitions/{eid}/predictor")


# ---------------------------------------------------------------- fetching

def target_saturday(today=None):
    """The Saturday to lead with — today, if today happens to be Saturday.

    The daily rebuild runs early Eastern, so on game day this returns today and
    the page shows the slate you are actually about to watch. Sunday through
    Friday it returns the coming Saturday.
    """
    today = today or dt.datetime.now(ET).date()
    return today + dt.timedelta(days=(5 - today.weekday()) % 7)


def _request(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_fpi(year):
    """Best effort. Returns {team_id: {...}}, or {} if anything goes wrong.

    The core-v2 list endpoint usually answers with bare {"$ref": ...} items
    rather than inline stats, which is why an earlier build produced empty FPI
    for every team. Detect that and expand the refs concurrently.
    """
    url = FPI_URL.format(year=year)
    data = None
    for label, headers in HEADER_PROFILES:
        try:
            data = _request(url, headers)
            break
        except Exception:
            continue
    if not data:
        print("  FPI unavailable - building without it", file=sys.stderr)
        return {}

    items = data.get("items") or []
    if not items:
        print("  FPI returned no items - building without it", file=sys.stderr)
        return {}

    # Expand any item that is only a reference.
    refs = [i["$ref"] for i in items
            if isinstance(i, dict) and "$ref" in i and "categories" not in i]
    if refs:
        from concurrent.futures import ThreadPoolExecutor

        def pull(u):
            try:
                return _request(u, HEADER_PROFILES[0][1])
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            items = [x for x in pool.map(pull, refs) if x]

    out = {}
    for item in items:
        ref = (item.get("team") or {}).get("$ref") or item.get("$ref") or ""
        m = re.search(r"/teams/(\d+)", ref)
        if not m:
            continue
        vals = {}
        for cat in item.get("categories", []):
            for st in cat.get("stats", []):
                name = (st.get("name") or st.get("abbreviation") or "").lower()
                if not name:
                    continue
                v = st.get("displayValue")
                if v is None:
                    v = st.get("value")
                vals[name] = v
        if vals:
            out[m.group(1)] = {
                "fpi":   vals.get("fpi"),
                "rank":  vals.get("fpirank") or vals.get("rank"),
                "projw": vals.get("projectedwins") or vals.get("proj w"),
                "projl": vals.get("projectedlosses") or vals.get("proj l"),
                "sos":   vals.get("strengthofschedulerank")
                         or vals.get("strengthofschedule") or vals.get("sos"),
            }

    if out:
        print(f"  FPI: {len(out)} teams", file=sys.stderr)
    else:
        print("  FPI parsed 0 teams - field names may have changed",
              file=sys.stderr)
    return out


def fetch(day):
    """Try each host/header combination until one answers with JSON."""
    attempts = []
    for url_tpl in API_HOSTS:
        url = url_tpl.format(ymd=day.strftime("%Y%m%d"))
        for label, headers in HEADER_PROFILES:
            try:
                data = _request(url, headers)
                host = url.split("/")[2]
                print(f"  fetched via {host} [{label}]", file=sys.stderr)
                return data
            except urllib.error.HTTPError as e:
                attempts.append(f"{url.split('/')[2]} [{label}] -> HTTP {e.code}")
            except urllib.error.URLError as e:
                attempts.append(f"{url.split('/')[2]} [{label}] -> {e.reason}")
            except json.JSONDecodeError:
                attempts.append(f"{url.split('/')[2]} [{label}] -> not JSON")

    detail = "\n    ".join(attempts)
    sys.exit(
        f"Every attempt to reach ESPN for {day} failed:\n    {detail}\n\n"
        "If all of them are 403, ESPN is refusing this client outright — most\n"
        "likely blocking cloud/datacenter IP ranges rather than the headers.\n"
        "In that case the build has to move to a different data source or run\n"
        "somewhere with a residential IP.")


def normalise(payload, fpi=None):
    """ESPN events -> flat game dicts. Returns (games, unknown_conf_ids)."""
    fpi = fpi or {}
    games, unknown = [], {}
    for ev in payload.get("events", []):
        comp = ev["competitions"][0]

        # Prefer the link ESPN supplies; fall back to building one from the id.
        espn = ""
        for l in (ev.get("links") or []):
            rels = l.get("rel") or []
            if "summary" in rels or "desktop" in rels:
                espn = l.get("href") or ""
                if espn:
                    break
        if not espn and ev.get("id"):
            espn = ("https://www.espn.com/college-football/game/_/gameId/"
                    + str(ev["id"]))
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        if "home" not in sides or "away" not in sides:
            continue

        nets = []
        for b in comp.get("broadcasts", []):
            nets += b.get("names", [])
        net = NETWORK_ALIASES.get(nets[0], nets[0]) if nets else ""

        # Betting lines ride along in the same response, so this costs no extra
        # request. They are absent for games more than a week or two out, and
        # every field here is optional — treat a missing block as "no line yet"
        # rather than an error.
        # Season leaders. Two shapes exist and they mean different things:
        # competition-level `leaders` is the GAME leader per category - one
        # entry, awarded to whichever side leads - while each competitor
        # carries its own `leaders`. Only the second gives both teams a row,
        # so prefer it and keep the first as a fallback.
        def read_leaders(node):
            out = []
            for cat in (node.get("leaders") or []):
                label = (cat.get("shortDisplayName") or cat.get("displayName")
                         or cat.get("abbreviation") or cat.get("name") or "")
                if not label:
                    continue
                for L in (cat.get("leaders") or [])[:1]:
                    ath = (L.get("athlete") or {}) or {}
                    who = ath.get("shortName") or ath.get("displayName") or ""
                    val = L.get("displayValue") or ""
                    if val:
                        out.append({"cat": label, "who": who, "val": val})
            return out

        # fallback map, keyed by team id, from the competition-level block
        game_leaders = {}
        for cat in (comp.get("leaders") or []):
            label = (cat.get("shortDisplayName") or cat.get("displayName")
                     or cat.get("abbreviation") or cat.get("name") or "")
            if not label:
                continue
            for L in (cat.get("leaders") or []):
                tid = str(((L.get("team") or {}).get("id")) or "")
                ath = (L.get("athlete") or {}) or {}
                val = L.get("displayValue") or ""
                if tid and val:
                    game_leaders.setdefault(tid, []).append({
                        "cat": label,
                        "who": ath.get("shortName") or ath.get("displayName") or "",
                        "val": val})

        odds = (comp.get("odds") or [{}])[0] or {}
        spread = odds.get("spread")
        try:
            mag = abs(float(spread)) if spread is not None else None
        except (TypeError, ValueError):
            mag = None
        line = {
            "detail": odds.get("details") or "",
            "ou": odds.get("overUnder"),
            "mag": mag,
        }

        def side(which):
            c = sides[which]
            t = c["team"]
            cid = str(t.get("conferenceId", ""))
            conf = CONFERENCES.get(cid, "FCS")
            if cid and cid not in CONFERENCES and cid != "":
                unknown.setdefault(cid, t.get("displayName", "?"))
            rank = (c.get("curatedRank") or {}).get("current")
            colour = t.get("color") or "2c4a70"

            # Overall record. ESPN returns several (home, away, conference);
            # the one wanted is type "total". Records are current as of the
            # build, not as of that game — fine for this week, slightly ahead
            # of itself on the later tabs.
            recs = {}
            for r in (c.get("records") or []):
                key = (r.get("type") or r.get("name") or "").lower()
                if key and r.get("summary"):
                    recs[key] = r["summary"]
            rec = (recs.get("total") or recs.get("overall")
                   or (list(recs.values())[0] if recs else ""))
            side_odds = odds.get(f"{which}TeamOdds") or {}
            fav = bool(side_odds.get("favorite"))
            # "-3.5" against the favourite, "+3.5" against the dog. A pick'em
            # (spread 0) gets "PK", which is how it is written everywhere.
            if mag is None:
                sp = ""
            elif mag == 0:
                sp = "PK"
            else:
                sp = ("-" if fav else "+") + (f"{mag:g}")
            return {
                "name": t.get("shortDisplayName") or t.get("location"),
                "conf": conf,
                "rank": rank if rank and rank <= 25 else None,
                "colour": "#" + colour.lstrip("#"),
                "spread": sp,
                "fav": fav,
                "rec": rec,
                "recs": recs,
                "leaders": (read_leaders(c)
                            or game_leaders.get(str(t.get("id") or ""), [])),
                "fpi": fpi.get(str(t.get("id") or "")) or {},
            }

        kick = dt.datetime.fromisoformat(
            comp["date"].replace("Z", "+00:00")).astimezone(ET)

        # ESPN parks games with no assigned window at midnight Eastern. Showing
        # those as "12:00 AM" is worse than saying so - the third week is full
        # of them until the networks make their selections.
        tbd = (kick.hour == 0 and kick.minute == 0)

        games.append({
            "kick": kick,
            "tbd": tbd,
            "net": net,
            "line": line,
            "espn": espn,
            "eid": str(ev.get("id") or ""),
            "pred": None,
            "away": side("away"),
            "home": side("home"),
        })
    games.sort(key=lambda g: g["kick"])
    return games, unknown


# ---------------------------------------------------------------- rendering

def ink(hexcolour):
    r, g, b = (int(hexcolour[i:i + 2], 16) for i in (1, 3, 5))
    return "#10233d" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 150 else "#ffffff"


def clock(t):
    h = t.strftime("%I").lstrip("0") or "12"
    return f"{h}:{t.strftime('%M')}", t.strftime("%p")


def lanes_for(games, span, col_of):
    """Pack overlapping games into stacked lanes within one network row."""
    lanes = []
    for g in games:
        s, e = col_of(g["kick"]), col_of(g["kick"]) + span
        lane = next((L for L in lanes
                     if all(col_of(x["kick"]) + span <= s or col_of(x["kick"]) >= e
                            for x in L)), None)
        if lane is None:
            lane = []
            lanes.append(lane)
        lane.append(g)
    return lanes


def render_week(games, day):
    tv = [g for g in games if g["net"] in GRID_NETWORKS]
    stream = [g for g in games if g["net"] not in GRID_NETWORKS]

    if not tv:
        raise SystemExit("No games matched GRID_NETWORKS — check the alias map.")

    # Grid runs in 15-minute columns from the first kickoff to the last + 3.5h.
    origin = min(g["kick"] for g in tv).replace(minute=0)
    last = max(g["kick"] for g in tv)
    span = 14                                    # 3.5 hours
    cols = int((last - origin).total_seconds() // 900) + span
    col_of = lambda t: int((t - origin).total_seconds() // 900) + 2

    by_net = defaultdict(list)
    for g in tv:
        by_net[g["net"]].append(g)

    counts = defaultdict(int)
    for g in games:
        for c in {g["away"]["conf"], g["home"]["conf"]}:
            counts[c] += 1

    payload = {
        "date_long": day.strftime("%A, %B ") + str(day.day),
        "date_short": (day.strftime("%b. ") + str(day.day)).upper(),
        "tab": day.strftime("%b ") + str(day.day),
        "cols": cols,
        "span": span,
        "origin": origin.isoformat(),
        "ticks": [
            {"col": i + 2,
             "iso": (origin + dt.timedelta(minutes=15 * i)).isoformat(),
             "time": clock(origin + dt.timedelta(minutes=15 * i))[0],
             "ap": clock(origin + dt.timedelta(minutes=15 * i))[1]}
            for i in range(0, cols, 2)
        ],
        "rows": [],
        "stream": [],
        "chips": ([{"key": "ALL", "label": "All games", "n": len(games)}] +
                  [{"key": c, "label": c, "n": counts[c]}
                   for c in CONF_ORDER if counts.get(c)]),
    }

    for net in GRID_NETWORKS:
        if net not in by_net:
            continue
        lanes = lanes_for(by_net[net], span, col_of)
        payload["rows"].append({
            "net": net,
            "lanes": len(lanes),
            "games": [
                {
                    "lane": i + 1,
                    "col": col_of(g["kick"]),
                    "conf": f'|{g["away"]["conf"]}|{g["home"]["conf"]}|',
                    "time": " ".join(clock(g["kick"])),
                    "iso": g["kick"].isoformat(),
                    "tbd": g.get("tbd", False),
                    "line": g["line"],
                    "espn": g["espn"],
                    "pred": g.get("pred"),
                    "away": g["away"], "home": g["home"],
                    "away_ink": ink(g["away"]["colour"]),
                    "home_ink": ink(g["home"]["colour"]),
                }
                for i, lane in enumerate(lanes) for g in lane
            ],
        })

    for g in sorted(stream, key=lambda x: x["kick"]):
        t, ap = clock(g["kick"])
        payload["stream"].append({
            "time": t, "ap": ap,
            "iso": g["kick"].isoformat(),
            "tbd": g.get("tbd", False),
            "badge": STREAM_BADGES.get(g["net"], "espnplus"),
            "net": g["net"] or "Streaming",
            "conf": f'|{g["away"]["conf"]}|{g["home"]["conf"]}|',
            "match": (f'{"#" + str(g["away"]["rank"]) + " " if g["away"]["rank"] else ""}'
                      f'{g["away"]["name"]} at '
                      f'{"#" + str(g["home"]["rank"]) + " " if g["home"]["rank"] else ""}'
                      f'{g["home"]["name"]}'),
        })

    payload["saturday"] = day.isoformat()
    return payload


def render_page(weeks, template_path="template.html"):
    doc = {
        "generated": dt.datetime.now(ET).isoformat(timespec="seconds"),
        "weeks": weeks,
    }
    tpl = open(template_path, encoding="utf-8").read()
    page = (tpl.replace("/*__DATA__*/null", json.dumps(doc))
               .replace("__APP_NAME__", APP_NAME)
               .replace("__APP_SHORT__", APP_SHORT)
               .replace("__SITE_URL__", SITE_URL.rstrip("/")))
    return page, doc


# ---------------------------------------------------------------- cli

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="first Saturday; defaults to the next one")
    p.add_argument("--weeks", type=int, default=3,
                   help="how many Saturdays to bake in (default 3)")
    p.add_argument("--predict-weeks", type=int, default=1, dest="predict_weeks",
                   help="how many of those weeks get matchup predictions "
                        "(one request per game; default 1, 0 disables)")
    p.add_argument("--out", default="public/index.html",
                   help="HTML output path (Firebase Hosting serves this dir)")
    p.add_argument("--json", dest="json_out", default="public/schedule.json",
                   help="machine-readable feed; '' to skip")
    a = p.parse_args()

    first = dt.date.fromisoformat(a.date) if a.date else target_saturday()

    # Season year: a January game belongs to the previous season.
    season = first.year if first.month >= 7 else first.year - 1
    fpi = fetch_fpi(season)

    weeks, unknown, stray = [], {}, set()

    for i in range(max(1, a.weeks)):
        day = first + dt.timedelta(days=7 * i)
        games, unk = normalise(fetch(day), fpi)
        unknown.update(unk)
        stray |= {g["net"] for g in games
                  if g["net"] and g["net"] not in GRID_NETWORKS
                  and g["net"] not in STREAM_BADGES}

        if not games:
            print(f"  {day}: no games returned, skipping", file=sys.stderr)
            continue

        if i < a.predict_weeks:
            got = add_predictions(games)
            print(f"  {day}: predictions for {got}/{len(games)} games",
                  file=sys.stderr)

        try:
            weeks.append(render_week(games, day))
            print(f"  {day}: {len(games)} games", file=sys.stderr)
        except SystemExit as e:
            # One bad week should not sink the whole page.
            print(f"  {day}: skipped ({e})", file=sys.stderr)

    if not weeks:
        raise SystemExit("No weeks could be built.")

    if unknown:
        print("  unmapped conference ids (add to CONFERENCES):", file=sys.stderr)
        for cid, example in sorted(unknown.items()):
            print(f"    {cid}  e.g. {example}", file=sys.stderr)
    if stray:
        print(f"  networks sent to the streaming list: {', '.join(sorted(stray))}",
              file=sys.stderr)

    page, doc = render_page(weeks)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"  wrote {a.out}", file=sys.stderr)

    if a.json_out:
        os.makedirs(os.path.dirname(a.json_out) or ".", exist_ok=True)
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1)
        print(f"  wrote {a.json_out}", file=sys.stderr)

    # Home-screen icons and the manifest that Android reads. iOS uses the
    # apple-touch-icon link in the page instead, but wants the same PNG.
    outdir = os.path.dirname(a.out) or "."
    written = icons.build(outdir)
    manifest = {
        "name": APP_NAME,
        "short_name": APP_SHORT,
        "start_url": "./",
        "display": "standalone",
        "orientation": "landscape",
        "background_color": "#081729",
        "theme_color": "#0d2340",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png",
             "purpose": "any"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "any"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }
    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print(f"  wrote manifest.json and {len(written)} icons", file=sys.stderr)


if __name__ == "__main__":
    main()
