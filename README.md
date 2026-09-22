# College football TV grid

A single web page showing every televised game for the coming Saturdays, laid
out by network across a time grid, filterable by conference. It rebuilds itself
daily on GitHub Actions and publishes to Firebase Hosting, so it lives at one
URL you can bookmark. No email, no app to install, nothing running at home.

> **Setting this up from a Windows PC?** Everything below works there, and there
> is a browser-only path that needs nothing installed at all. See
> [Setting it up](#setting-it-up).

```
build.py                       fetch -> normalise -> render -> public/
template.html                  the page; build.py injects a JSON blob into it
check_target.py                refuses to deploy anywhere but the cfb site
icons.py                       draws the football mark and the link-preview card
firebase.json                  Hosting config: cfb target, cache rules, CORS
public/                        build output (gitignored, regenerated each run)
  index.html                     the page
  schedule.json                  same data, for anything else that wants it
.github/workflows/publish.yml  daily rebuild and deploy
Makefile / tasks.py            local shortcuts (make for Unix, tasks.py anywhere)
requirements.txt               empty except tzdata on Windows
```

## How it works

The schedule is fully static. Every build fetches from ESPN server-side and
bakes the result into the HTML, so the grid renders with no network calls and
can't break because a browser blocked a cross-origin request. Live scores are
the one exception — see below.

Each build bakes in **three Saturdays**, switchable with tabs at the top. That
way the URL is useful whenever you open it, not just on the day it was built.

The rebuild runs **daily**, not weekly. Networks assign kickoff windows on six-
and twelve-day selection, so a page built only on Mondays would be wrong by
Thursday. The page shows when it was last built, and warns on itself if that was
more than three days ago — so a silently failing build is visible rather than
quietly serving stale times.

Conference selection persists in `localStorage`, private to your browser. If
storage is blocked the page just defaults to showing everything.

### What is on the page

- **Time grid by network**, 15-minute columns, overlapping games stacked into
  lanes automatically.
- **One bar per game**, split between the two team colours and stitched at the
  seam with a badge. No kickoff text — the bar's position is the time.
- **Click any game** for a panel: live score and clock, matchup predictor,
  network, kickoff, spread, over/under, a link to the game on ESPN, and a Teams
  tab comparing records, splits, FPI, projected wins and season leaders.
- **Team search** that combines with the conference filter rather than
  replacing it.
- **Collapsible conference chips**, collapsed by default on narrow screens.
- **Local time zones** throughout, with an ET toggle and day markers for games
  that cross midnight where the viewer is.

### Live scores

The only part of the page that talks to the network. When the week on screen is
today's (or yesterday's — a late kickoff finishes after midnight Eastern), the
browser fetches the ESPN scoreboard directly and paints scores onto the bars.

The two scores flank the centre badge, so a bar reads `Ohio State 21 @ 17 Texas`,
and the leading side shows at full strength. **The badge carries the period**:
`Q3`, `HALF`, `OT`, `2OT` while a game is being played, colour-coded red for
regulation and amber for overtime. It sits over the seam, so the room it needs
is shared between the two teams rather than taken from the home side.

Once a game is final the badge goes back to `@` and the whole bar dims — muted
plus a score already says "this is finished", so spelling out FINAL would say it
twice. Games that have not kicked off look exactly as they do with no live data
at all. Postponed and cancelled games are detected and never render as a 0–0
final. The full clock stays in the panel.

Host choice matters here. `site.api.espn.com` answers scripts but refuses
browsers; `site.web.api.espn.com` is the host ESPN's own front end calls and
returns `access-control-allow-origin: *`, so the page reads it with no proxy in
between.

Polling is 30s while anything is in progress, 120s on a game day before kickoff,
and stops once every game on the slate is final. A hidden tab does not poll.
After three consecutive failures it gives up and says `scores unavailable`
rather than retrying forever. **The schedule never depends on any of this
working.**

One consequence worth knowing: unlike the rest of the app, this cost scales with
viewers. Each open tab polls ESPN itself, so a thousand people watching on a
Saturday is a thousand clients hitting ESPN every 30 seconds. Fine at family
scale; to go wider, the fix is a small scheduled job writing a `live.json` onto
Hosting and pointing the page at that instead.

## Setting it up

### Option A — browser only, nothing installed

The build runs on GitHub's servers. A local machine is only useful for changing
the design.

1. **Create the repo.** On github.com, make a repo and upload these files
   through the web uploader. Keep `.github/workflows/` intact.
2. **Make the Hosting site.** Firebase console → the `cfb-schedule-grid`
   project → Hosting → **Get started**. The default site is named after the
   project id, so the URL is `https://cfb-schedule-grid.web.app`.

   ```json
   {
     "projects": { "default": "your-project-id" },
     "targets": {
       "your-project-id": {
         "hosting": { "cfb": ["smith-cfb-grid"] }
       }
     }
   }
   ```

4. **Add credentials.** Settings → Secrets and variables → Actions:

   | Kind     | Name                       | Value                              |
   |----------|----------------------------|------------------------------------|
   | Secret   | `FIREBASE_SERVICE_ACCOUNT` | service account JSON, pasted whole |
   | Variable | `FIREBASE_PROJECT_ID`      | your project id                    |

   The service account comes from the Google Cloud console for the project, with
   the **Firebase Hosting Admin** role.

5. **Run it.** Actions tab → *Publish college football TV grid* → **Run
   workflow**. To build without publishing, untick *deploy* and download the
   artifact from the run summary.

Your URL is `https://<site-name>.web.app`. It refreshes daily from then on.

### Option B — locally

```bash
# macOS
brew install node && npm install -g firebase-tools

# Windows
winget install Python.Python.3.12
winget install OpenJS.NodeJS
npm install -g firebase-tools
```

Then:

```bash
firebase login
pip install -r requirements.txt        # only does anything on Windows
cp .firebaserc.example .firebaserc     # add your project id and site name
python tasks.py setup
```

`build.py` needs Python 3.9+ and, on macOS and Linux, nothing else.

**On Windows, `tzdata` is not optional.** Every kickoff here is US Eastern, and
Windows ships no IANA time zone database. Without it `build.py` stops with a
message telling you to install it, rather than producing wrong times.

Use `tasks.py` on any OS, or `make` on macOS and Linux:

| Task           | tasks.py                                          | make               |
|----------------|---------------------------------------------------|--------------------|
| Check setup    | `python tasks.py setup`                           | `make setup`       |
| Build + open   | `python tasks.py preview`                         | `make preview`     |
| Create site    | `python tasks.py init-site --site smith-cfb-grid` | `make init-site`   |
| Publish        | `python tasks.py deploy`                          | `make deploy`      |

Add `--date 2026-09-12` or `--weeks 1` to any of them.

## Deploy target guard

This project lives in its own Firebase project, so a deploy cannot reach
anything else. The `cfb` hosting target is kept anyway, because a Firebase
deploy replaces a site's entire contents and the guard catches a mistyped
project id before that happens rather than after:

- `firebase.json` declares `"target": "cfb"` rather than a bare hosting block.
- Every deploy is scoped `--only hosting:cfb`.
- `check_target.py` runs before both the local and the CI deploy and refuses to
  continue if `.firebaserc` is missing, still holds placeholders, has no `cfb`
  binding, or binds `cfb` to more than one site.

Check it any time without deploying: `python check_target.py`

## The JSON feed

Each build also writes `public/schedule.json` — the same data the page renders
from, served with `Access-Control-Allow-Origin: *` and a 15-minute cache, in
case you later want the dashboard to show a summary card:

```js
const r = await fetch("https://<site>.web.app/schedule.json");
const { generated, weeks } = await r.json();
// weeks[].rows[].games[] -> { col, time, conf, away:{name,rank,colour}, home:{...} }
```

Drop it with `--json ''` if nothing consumes it.

## What I could not test

Written without network access to ESPN, so these are reasoned from the API's
shape rather than verified against a live response:

- **Exact JSON field names.** `normalise()` expects
  `competitions[0].broadcasts[].names`, `competitors[].curatedRank.current`
  and `team.conferenceId`. A rename shows up as a `KeyError` on the first run.
- **Conference id numbers** in `CONFERENCES`. Any id the script doesn't
  recognise is printed with an example team, so a wrong entry surfaces as a
  specific line to fix rather than a silent mislabel. Teams with no id fall
  through to FCS, which is the right default.
- **Network name strings.** `NETWORK_ALIASES` normalises the ones I expect
  ("Big Ten Network" → BTN). Anything unrecognised lands in the streaming list
  instead of getting a grid row, and the script prints what went there.

The Firebase deploy is also untested from here.

Everything downstream of the fetch is tested: parsing, conference tagging, lane
packing for networks with overlapping games, column math, multi-week rendering,
filtering, both output formats, and the error paths for bad config and network
failure.

**Run one build and look at it before trusting the URL.**

## Things that will eventually break

- **ESPN's endpoint is undocumented.** Stable and widely used, but nobody owes
  you notice before changing it. If the page stops updating, the stamp at the
  top will start warning and the Actions log will say why.
- **Kickoff windows move.** Daily rebuilds keep up with six- and twelve-day
  selection, but the third tab is always the least settled.
- **Cron drift.** GitHub delays scheduled jobs under load.
- **Hosting overwrites.** Each deploy replaces the whole site contents, which is
  what `check_target.py` exists to contain.

## Tuning

Everything worth changing sits at the top of two files.

`build.py`:
- `APP_NAME` / `APP_SHORT` — page heading, browser tab, home-screen label.
- `SITE_URL` — used for the absolute Open Graph image URL in link previews.
- `GRID_NETWORKS` — which networks get a row, in display order.
- `CONF_ORDER` — order of the filter chips.

`icons.py`:
- `STYLE` — `football`, `football-bars`, `bars`, `cfb`, or `cfb-schedule`.
- `LEATHER`, `TILT`, `BALL_A`, `BALL_B` — the football's look.
- Or drop an `icon-source.png` in the repo root and it is used instead.

Command line:
- `--weeks N` — how many Saturdays to bake in.
- `--date YYYY-MM-DD` — build a specific week.
