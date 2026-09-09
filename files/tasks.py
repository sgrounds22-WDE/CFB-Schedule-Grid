#!/usr/bin/env python3
"""
Cross-platform task runner. Windows has no `make`, and the Makefile is full of
Unix shell (`test -f`, `command -v`, `open`). This does the same jobs using
only Python, so it behaves identically on Windows, macOS and Linux.

  python tasks.py setup
  python tasks.py preview
  python tasks.py preview --date 2026-09-12
  python tasks.py init-site --site smith-cfb-grid
  python tasks.py deploy
  python tasks.py check

Mac users can keep using `make`; the two are interchangeable.
"""

import argparse
import os
import shutil
import subprocess
import sys
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
OUT = os.path.join("public", "index.html")

# On Windows the Firebase CLI installs as firebase.cmd, which subprocess will
# not find without the extension unless we go through the shell.
FIREBASE = shutil.which("firebase") or shutil.which("firebase.cmd")


def run(cmd, **kw):
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=HERE, **kw)
    if r.returncode:
        sys.exit(r.returncode)


def need_firebase():
    if not FIREBASE:
        sys.exit("Firebase CLI not found.\n"
                 "  Windows:  winget install OpenJS.NodeJS  then  npm i -g firebase-tools\n"
                 "  macOS:    brew install node             then  npm i -g firebase-tools\n"
                 "Then run:  firebase login")
    return FIREBASE


def build(date, weeks=None):
    cmd = [PY, "build.py"]
    if date:
        cmd += ["--date", date]
    if weeks:
        cmd += ["--weeks", str(weeks)]
    run(cmd)


# ---------------------------------------------------------------- tasks

def t_setup(a):
    v = sys.version_info
    if v < (3, 9):
        sys.exit(f"Need Python 3.9+, found {v.major}.{v.minor}")
    print(f"python {v.major}.{v.minor}.{v.micro} ok")

    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("America/New_York")
        print("time zone data ok")
    except Exception:
        print("time zone data MISSING — run:  pip install tzdata")

    print(f"firebase CLI {'ok' if FIREBASE else 'MISSING (npm i -g firebase-tools)'}")

    if os.path.exists(os.path.join(HERE, ".firebaserc")):
        run([PY, "check_target.py"])
    else:
        print(".firebaserc missing — copy .firebaserc.example to .firebaserc")




def t_build(a):
    build(a.date, a.weeks)


def t_preview(a):
    build(a.date, a.weeks)
    path = os.path.join(HERE, OUT)
    print("opening", path)
    webbrowser.open("file://" + path.replace(os.sep, "/"))


def t_init_site(a):
    fb = need_firebase()
    if not a.site:
        sys.exit("Pass --site. Names are globally unique across all of "
                 "Firebase, so prefix it: --site smith-cfb-grid")
    run([fb, "hosting:sites:create", a.site], shell=os.name == "nt")
    run([fb, "target:apply", "hosting", "cfb", a.site], shell=os.name == "nt")
    print(f"\nbound cfb -> {a.site}")
    print(f"link will be https://{a.site}.web.app")
    print("commit .firebaserc so CI picks up the binding")


def t_deploy(a):
    fb = need_firebase()
    run([PY, "check_target.py"])          # refuses to touch the default site
    build(a.date, a.weeks)
    run([fb, "deploy", "--only", "hosting:cfb"], shell=os.name == "nt")


def t_check(a):
    build("2026-09-12", 2)
    import json
    d = json.load(open(os.path.join(HERE, "public", "schedule.json"),
                       encoding="utf-8"))
    print("--- sanity ---")
    print("generated:", d["generated"])
    for w in d["weeks"]:
        print(f"  {w['saturday']}  networks={len(w['rows'])} "
              f"streaming={len(w['stream'])} "
              f"chips={[(c['label'], c['n']) for c in w['chips']]}")


def t_clean(a):
    for p in ["public/index.html", "public/schedule.json", "out",
              "__pycache__", ".firebase"]:
        full = os.path.join(HERE, p)
        if os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)
        elif os.path.exists(full):
            os.remove(full)
    print("cleaned")


TASKS = {
    "setup": t_setup, "build": t_build, "preview": t_preview,
    "init-site": t_init_site, "deploy": t_deploy,
    "check": t_check, "clean": t_clean,
}


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task", choices=sorted(TASKS))
    p.add_argument("--date", help="Saturday to build (YYYY-MM-DD)")
    p.add_argument("--site", help="Hosting site name, for init-site")
    p.add_argument("--weeks", type=int, help="how many Saturdays to bake in")
    a = p.parse_args()
    TASKS[a.task](a)


if __name__ == "__main__":
    main()
