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

import argparse, datetime as dt, json, os, sys, urllib.request
from collections import defaultdict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Every kickoff in this script is Eastern. Linux and macOS ship the IANA time
# zone database; Windows does not, so zoneinfo there depends on the `tzdata`
# package. Fail with the fix rather than a bare lookup error.
try:
    ET = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    sys.exit("No time zone database found.\n"
             "On Windows, run:  pip install tzdata")
API = ("https://site.api.espn.com/apis/site/v2/sports/football/college-football"
       "/scoreboard?dates={ymd}&groups=80&limit=400")

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
                 "TNT", "FS1", "USA", "ACCN", "SECN", "BTN", "CBSSN"]

NETWORK_ALIASES = {
    "ACC Network": "ACCN", "SEC Network": "SECN", "Big Ten Network": "BTN",
    "CBS Sports Network": "CBSSN", "The CW": "CW", "USA Network": "USA",
    "ESPN/Disney+": "ESPN", "ABC/Disney+": "ABC", "TNT/HBO Max": "TNT",
}

STREAM_BADGES = {"ESPN+": "espnplus", "SECN+": "secnplus",
                 "ACCNX": "accnx", "MW+": "mwplus", "ESPN3": "espnplus"}


# ---------------------------------------------------------------- fetching

def next_saturday(today=None):
    today = today or dt.datetime.now(ET).date()
    return today + dt.timedelta(days=(5 - today.weekday()) % 7 or 7)


def fetch(day):
    url = API.format(ymd=day.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "cfb-tv-grid/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"ESPN returned HTTP {e.code} for {day}.\n"
                 "If this is 403 or 429 you are probably rate limited or behind "
                 "a proxy; if 404, the endpoint moved.\n" + url)
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach ESPN: {e.reason}\n"
                 "Check your connection, VPN, or corporate firewall.")
    except json.JSONDecodeError:
        sys.exit("ESPN returned something that is not JSON. The endpoint may "
                 "have changed.\n" + url)


def normalise(payload):
    """ESPN events -> flat game dicts. Returns (games, unknown_conf_ids)."""
    games, unknown = [], {}
    for ev in payload.get("events", []):
        comp = ev["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        if "home" not in sides or "away" not in sides:
            continue

        nets = []
        for b in comp.get("broadcasts", []):
            nets += b.get("names", [])
        net = NETWORK_ALIASES.get(nets[0], nets[0]) if nets else ""

        def side(which):
            c = sides[which]
            t = c["team"]
            cid = str(t.get("conferenceId", ""))
            conf = CONFERENCES.get(cid, "FCS")
            if cid and cid not in CONFERENCES and cid != "":
                unknown.setdefault(cid, t.get("displayName", "?"))
            rank = (c.get("curatedRank") or {}).get("current")
            colour = t.get("color") or "2c4a70"
            return {
                "name": t.get("shortDisplayName") or t.get("location"),
                "conf": conf,
                "rank": rank if rank and rank <= 25 else None,
                "colour": "#" + colour.lstrip("#"),
            }

        games.append({
            "kick": dt.datetime.fromisoformat(
                comp["date"].replace("Z", "+00:00")).astimezone(ET),
            "net": net,
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
        "ticks": [
            {"col": i + 2, "time": clock(origin + dt.timedelta(minutes=15 * i))[0],
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
    return tpl.replace("/*__DATA__*/null", json.dumps(doc)), doc


# ---------------------------------------------------------------- cli

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="first Saturday; defaults to the next one")
    p.add_argument("--weeks", type=int, default=3,
                   help="how many Saturdays to bake in (default 3)")
    p.add_argument("--out", default="public/index.html",
                   help="HTML output path (Firebase Hosting serves this dir)")
    p.add_argument("--json", dest="json_out", default="public/schedule.json",
                   help="machine-readable feed; '' to skip")
    a = p.parse_args()

    first = dt.date.fromisoformat(a.date) if a.date else next_saturday()
    weeks, unknown, stray = [], {}, set()

    for i in range(max(1, a.weeks)):
        day = first + dt.timedelta(days=7 * i)
        games, unk = normalise(fetch(day))
        unknown.update(unk)
        stray |= {g["net"] for g in games
                  if g["net"] and g["net"] not in GRID_NETWORKS
                  and g["net"] not in STREAM_BADGES}

        if not games:
            print(f"  {day}: no games returned, skipping", file=sys.stderr)
            continue

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


if __name__ == "__main__":
    main()
