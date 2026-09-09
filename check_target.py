#!/usr/bin/env python3
"""
Preflight for `make deploy`.

The Family Dashboard is live on this project's default Hosting site, and a
Firebase deploy replaces a site's entire contents. So this project must only
ever deploy through the named "cfb" target, bound to its own site.

Exits non-zero if .firebaserc would let a deploy land somewhere unintended.
"""

import json
import os
import sys

RC = ".firebaserc"


def main():
    if not os.path.exists(RC):
        sys.exit(f"{RC} missing. Run: cp .firebaserc.example {RC}")

    try:
        rc = json.load(open(RC, encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"{RC} is not valid JSON: {e}")

    project = rc.get("projects", {}).get("default", "")
    sites = [s
             for proj in rc.get("targets", {}).values()
             for s in proj.get("hosting", {}).get("cfb", [])]

    if not project:
        sys.exit(f"No default project in {RC}.")

    if not sites:
        sys.exit(
            "The 'cfb' hosting target is not bound to a site.\n"
            "Without it, a deploy would go to the project default site — "
            "where the Family Dashboard lives — and overwrite it.\n"
            "Run: make init-site SITE=your-site-name")

    placeholders = [v for v in sites + [project] if v.startswith("YOUR_")]
    if placeholders:
        sys.exit(f"Placeholders still in {RC}: {', '.join(placeholders)}")

    if len(sites) > 1:
        sys.exit(f"'cfb' is bound to several sites ({', '.join(sites)}). "
                 "Bind it to exactly one.")

    print(f"cfb -> {sites[0]} on {project}  ok")
    print(f"       https://{sites[0]}.web.app")


if __name__ == "__main__":
    main()
