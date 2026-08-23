# fetch_github_stats.py
#!/usr/bin/env python3
"""
fetch_github_stats.py

Pulls contribution + lines-of-code statistics from GitHub and writes them
to assets/github_stats.json. gif_script.py reads that file (if present) and
renders a "$ contrib_stats" section in the terminal GIF; if the file is
missing, that section is skipped and the GIF still builds normally.

Run this BEFORE gif_script.py:

    export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
    export GITHUB_USERNAME=yourusername
    python fetch_github_stats.py
    python gif_script.py

------------------------------------------------------------------------
WHY A PERSONAL ACCESS TOKEN (PAT) IS REQUIRED
------------------------------------------------------------------------
- The daily contribution calendar (source of stats #1 and #3 below) is
  only exposed via GitHub's GraphQL API, and GraphQL has no anonymous
  mode at all — every request must be authenticated, even for a fully
  public profile.
- Lines-of-code stats (#4) come from the REST "stats/contributors"
  endpoint. It works unauthenticated but is capped at 60 requests/hour,
  which you'll blow through instantly once you have more than a couple
  repos. Authenticated requests get 5,000/hour.
- Hourly commit activity (#2) comes from the public Events API, which
  technically doesn't require auth — but GitHub only retains ~90 days /
  ~300 events of public activity there, so treat it as a recent sample,
  not a lifetime total. There is no GitHub endpoint that returns
  full-history hourly commit timestamps.

WHICH TOKEN / SCOPES
---------------------
Classic PAT (https://github.com/settings/tokens -> "Tokens (classic)"):
  - `read:user`  -> required, unlocks the GraphQL contribution calendar
  - `repo`       -> only needed if you want PRIVATE repos included in
                    the lines-of-code total. Omit it to keep the token
                    restricted to public repos.

A fine-grained PAT also works: give it "Read-only" access to
"Contents" + "Metadata" for whichever repos you want counted, plus
account permission to read your profile.

NEVER hard-code the token in this file or commit it — always pass it
via the GITHUB_TOKEN environment variable.
"""

import os
import sys
import json
import time
import requests
from collections import defaultdict
from datetime import datetime, timezone

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME")
OUT_PATH = "assets/github_stats.json"

GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _require_auth():
    if not GITHUB_TOKEN or not GITHUB_USERNAME:
        print(
            "ERROR: GITHUB_TOKEN and GITHUB_USERNAME environment variables "
            "are required.\n"
            "  export GITHUB_TOKEN=ghp_xxx...\n"
            "  export GITHUB_USERNAME=yourusername\n"
            "See the top of this file for which token scopes you need.",
            file=sys.stderr,
        )
        sys.exit(1)


def _headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


# ------------------------------------------------------------------
# 1 & 3. Contribution calendar -> daily / day-of-week / weekly stats
# ------------------------------------------------------------------

CONTRIB_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_contribution_calendar():
    """GraphQL contribution calendar covers the trailing 12 months."""
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": CONTRIB_QUERY, "variables": {"login": GITHUB_USERNAME}},
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")

    calendar = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    total = calendar["totalContributions"]
    weeks = calendar["weeks"]

    by_weekday = defaultdict(int)
    days_with_data = 0

    for week in weeks:
        for day in week["contributionDays"]:
            date = datetime.fromisoformat(day["date"]).replace(tzinfo=timezone.utc)
            weekday = WEEKDAY_NAMES[date.weekday()]
            by_weekday[weekday] += day["contributionCount"]
            days_with_data += 1

    num_weeks = len(weeks) or 1
    avg_per_day = total / days_with_data if days_with_data else 0
    avg_per_week = total / num_weeks

    avg_by_weekday = {
        day: round(by_weekday.get(day, 0) / max(num_weeks, 1), 2)
        for day in WEEKDAY_NAMES
    }

    return {
        "total_contributions": total,
        "avg_per_day": round(avg_per_day, 2),
        "avg_per_week": round(avg_per_week, 2),
        "total_per_weekday": dict(by_weekday),
        "avg_per_weekday": avg_by_weekday,
        "weeks_covered": num_weeks,
    }


# ------------------------------------------------------------------
# 2. Hourly commit activity (best-effort, last ~90 days / 300 events)
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# 2. Hourly commit activity
#    Uses GitHub Commit Search API and converts timestamps to IST.
# ------------------------------------------------------------------

from zoneinfo import ZoneInfo


LOCAL_TIMEZONE = ZoneInfo("Asia/Kolkata")


def fetch_hourly_activity():
    """
    Estimate hourly commit activity using GitHub's Commit Search API.

    Unlike the public Events API, this works from actual commit timestamps.

    Important:
      - Search API covers public commits.
      - GitHub Search has a maximum result window, so we split the
        search into smaller time periods.
      - Commit timestamps are converted from UTC to Asia/Kolkata (IST).
    """

    hourly = defaultdict(int)

    # Search the recent period.
    #
    # We use 90 days here to keep the result comparable to the old
    # Events API implementation while obtaining actual commit data.
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=90)

    # GitHub Search can become restrictive with large result sets.
    # Split the 90-day period into 7-day windows.
    window_start = start
    commits_found = 0
    search_requests = 0

    while window_start < now:

        window_end = min(
            window_start + timedelta(days=7),
            now
        )

        # GitHub's date syntax is inclusive.
        query = (
            f"author:{GITHUB_USERNAME} "
            f"committer-date:{window_start.strftime('%Y-%m-%d')}"
            f"..{window_end.strftime('%Y-%m-%d')}"
        )

        page = 1

        while page <= 10:

            resp = requests.get(
                f"{REST_URL}/search/commits",
                headers={
                    **_headers(),
                    "Accept": "application/vnd.github+json",
                },
                params={
                    "q": query,
                    "per_page": 100,
                    "page": page,
                },
                timeout=30,
            )

            search_requests += 1

            if resp.status_code != 200:
                print(
                    f"WARNING: commit search failed "
                    f"({resp.status_code}): {resp.text[:300]}",
                    file=sys.stderr,
                )
                break

            data = resp.json()

            items = data.get("items", [])

            if not items:
                break

            for item in items:

                commit = item.get("commit") or {}

                committer = commit.get("committer") or {}

                timestamp = committer.get("date")

                if not timestamp:
                    continue

                try:
                    dt = datetime.fromisoformat(
                        timestamp.replace("Z", "+00:00")
                    )
                except ValueError:
                    continue

                # Convert UTC -> India Standard Time.
                local_dt = dt.astimezone(LOCAL_TIMEZONE)

                hourly[local_dt.hour] += 1
                commits_found += 1

            # Stop if this was the last page.
            if len(items) < 100:
                break

            page += 1

            # Small delay to be polite to GitHub.
            time.sleep(0.2)

        window_start = window_end

    counts = {
        str(h): hourly.get(h, 0)
        for h in range(24)
    }

    peak_hour = max(
        range(24),
        key=lambda h: counts[str(h)]
    )

    peak_count = counts[str(peak_hour)]

    # Human-readable daypart.
    if 5 <= peak_hour < 12:
        period = "Morning"
    elif 12 <= peak_hour < 17:
        period = "Afternoon"
    elif 17 <= peak_hour < 21:
        period = "Evening"
    else:
        period = "Night"

    return {
        "hourly_commit_counts": counts,

        "hourly_timezone": "Asia/Kolkata",
        "hourly_timezone_label": "IST (UTC+05:30)",

        "hourly_period_days": 90,
        "hourly_source": "GitHub Commit Search API",

        "commits_sampled": commits_found,
        "search_requests": search_requests,

        "peak_hour": peak_hour,
        "peak_hour_label": (
            f"{peak_hour:02d}:00–{peak_hour:02d}:59 IST"
        ),
        "peak_hour_commit_count": peak_count,
        "most_active_period": period,

        "hourly_caveat": (
            "Based on publicly searchable commits from the "
            "last ~90 days; timestamps converted to IST. "
            "This is an estimate of commit activity, not total "
            "coding activity."
        ),
    }

# ------------------------------------------------------------------
# 4. Lines of code (additions/deletions) across owned repos
# ------------------------------------------------------------------

def fetch_repos():
    repos = []
    page = 1
    while True:
        resp = requests.get(
            f"{REST_URL}/users/{GITHUB_USERNAME}/repos",
            headers=_headers(),
            params={"per_page": 100, "page": page, "type": "owner"},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        repos.extend(r["name"] for r in batch if not r.get("fork"))
        page += 1
    return repos


def fetch_lines_of_code(repos):
    total_additions = 0
    total_deletions = 0
    per_repo = {}

    for repo in repos:
        url = f"{REST_URL}/repos/{GITHUB_USERNAME}/{repo}/stats/contributors"
        resp = None
        for _attempt in range(3):  # GitHub computes stats async: 202 = "come back later"
            resp = requests.get(url, headers=_headers(), timeout=30)
            if resp.status_code == 202:
                time.sleep(2)
                continue
            break

        if resp is None or resp.status_code != 200:
            continue

        contributors = resp.json() or []
        added = deleted = 0
        for c in contributors:
            author = c.get("author") or {}
            if author.get("login") != GITHUB_USERNAME:
                continue
            for week in c.get("weeks", []):
                added += week.get("a", 0)
                deleted += week.get("d", 0)

        if added or deleted:
            per_repo[repo] = {"additions": added, "deletions": deleted}
            total_additions += added
            total_deletions += deleted

    return {
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "net_lines": total_additions - total_deletions,
        "per_repo": per_repo,
    }


def main():
    _require_auth()

    print("INFO: fetching contribution calendar...")
    contrib = fetch_contribution_calendar()

    print("INFO: fetching hourly activity (public events, best-effort)...")
    hourly = fetch_hourly_activity()

    print("INFO: listing owned repos...")
    repos = fetch_repos()
    print(
        f"INFO: found {len(repos)} owned repos, fetching lines-of-code stats "
        "(this can take a while — GitHub computes stats lazily on first request)..."
    )
    loc = fetch_lines_of_code(repos)

    stats = {
        "username": GITHUB_USERNAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **contrib,
        **hourly,
        **loc,
    }

    os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"\nINFO: wrote {OUT_PATH}")
    print(f"  total contributions : {stats['total_contributions']}")
    print(f"  avg / day            : {stats['avg_per_day']}")
    print(f"  avg / week           : {stats['avg_per_week']}")
    print(f"  total lines added    : {stats['total_additions']}")
    print(f"  total lines deleted  : {stats['total_deletions']}")


if __name__ == "__main__":
    main()
