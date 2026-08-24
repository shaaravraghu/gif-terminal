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
    daily_contributions = {}
    
    for week in weeks:
        for day in week["contributionDays"]:
            date = datetime.fromisoformat(day["date"]).replace(tzinfo=timezone.utc)
            weekday = WEEKDAY_NAMES[date.weekday()]
            by_weekday[weekday] += day["contributionCount"]
            days_with_data += 1
            date_string = day["date"]
            count = day["contributionCount"]
            daily_contributions[date_string] = count

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
        "daily_contributions": daily_contributions,
    }




def calculate_streak_metrics(daily_contributions):
    """
    Calculate activity streaks from GitHub contribution days.
    """

    dates = sorted(daily_contributions.keys())

    if not dates:
        return {
            "period_days": 365,
            "active_days": 0,
            "inactive_days": 0,
            "longest_streak": 0,
            "current_streak": 0,
            "average_active_day_contributions": 0,
        }

    active_days = sum(
        1
        for count in daily_contributions.values()
        if count > 0
    )

    total_days = len(daily_contributions)

    inactive_days = total_days - active_days

    longest_streak = 0
    current_streak = 0
    streak = 0

    previous_date = None

    for date_string in dates:

        date = datetime.fromisoformat(date_string).date()
        count = daily_contributions[date_string]

        if count > 0:

            if (
                previous_date is not None
                and date == previous_date + timedelta(days=1)
            ):
                streak += 1
            else:
                streak = 1

            longest_streak = max(
                longest_streak,
                streak
            )

        else:
            streak = 0

        previous_date = date

    # Current streak works backwards from the latest available day.
    current_streak = 0

    for date_string in reversed(dates):

        if daily_contributions[date_string] > 0:
            current_streak += 1
        else:
            break

    active_counts = [
        count
        for count in daily_contributions.values()
        if count > 0
    ]

    average_active_day_contributions = (
        sum(active_counts) / len(active_counts)
        if active_counts
        else 0
    )

    return {
        "period_days": total_days,
        "active_days": active_days,
        "inactive_days": inactive_days,
        "longest_streak": longest_streak,
        "current_streak": current_streak,
        "average_active_day_contributions": round(
            average_active_day_contributions,
            2
        ),
    }


def calculate_activity_acceleration(daily_contributions):
    """
    Calculate average daily GitHub contributions over multiple windows.
    """

    today = datetime.now(timezone.utc).date()

    windows = [30, 60, 90, 180, 365]

    result = {}

    for days in windows:

        cutoff = today - timedelta(days=days - 1)

        values = []

        for date_string, count in daily_contributions.items():

            date = datetime.fromisoformat(
                date_string
            ).date()

            if cutoff <= date <= today:
                values.append(count)

        result[f"{days}_day_average"] = round(
            sum(values) / days,
            2
        )

    # Useful derived acceleration indicators.
    a30 = result["30_day_average"]
    a90 = result["90_day_average"]
    a180 = result["180_day_average"]
    a365 = result["365_day_average"]

    result["30_vs_90_ratio"] = round(
        a30 / a90,
        3
    ) if a90 else None

    result["90_vs_180_ratio"] = round(
        a90 / a180,
        3
    ) if a180 else None

    result["90_vs_365_ratio"] = round(
        a90 / a365,
        3
    ) if a365 else None

    return result




def calculate_repository_concentration(commits):
    """
    Herfindahl-style repository concentration based on commit share.

    HHI:
        1.0  = all commits in one repository
        0.0  = extremely diversified
    """

    repo_counts = defaultdict(int)

    for commit in commits:

        repo = commit.get("repository")

        if repo:
            repo_counts[repo] += 1

    total = sum(repo_counts.values())

    if not total:
        return {
            "metric": "Herfindahl-Hirschman Index",
            "hhi": 0,
            "effective_repositories": 0,
            "repository_shares": {},
        }

    shares = {
        repo: count / total
        for repo, count in repo_counts.items()
    }

    hhi = sum(
        share ** 2
        for share in shares.values()
    )

    effective_repositories = (
        1 / hhi
        if hhi
        else 0
    )

    return {
        "metric": "Herfindahl-Hirschman Index",
        "basis": "commits",
        "period_days": ACTIVITY_DAYS,
        "hhi": round(hhi, 4),
        "effective_repositories": round(
            effective_repositories,
            2
        ),
        "repository_shares": {
            repo: round(share, 4)
            for repo, share in sorted(
                shares.items(),
                key=lambda x: x[1],
                reverse=True
            )
        },
        "repository_commits": dict(
            sorted(
                repo_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )
        ),
    }



def calculate_code_churn(loc):
    additions = loc["total_additions"]
    deletions = loc["total_deletions"]

    return {
        "additions": additions,
        "deletions": deletions,
        "total_churn": additions + deletions,
        "net_lines": additions - deletions,
        "deletion_ratio": round(
            deletions / additions,
            4
        ) if additions else 0,
        "deletion_percentage_of_churn": round(
            deletions / (additions + deletions) * 100,
            2
        ) if additions + deletions else 0,
    }


def calculate_repo_efficiency(per_repo):

    result = {}

    for repo, data in per_repo.items():

        additions = data["additions"]
        deletions = data["deletions"]
        commits = data["commits"]

        net_lines = additions - deletions
        churn = additions + deletions

        result[repo] = {
            "commits": commits,
            "additions": additions,
            "deletions": deletions,
            "net_lines": net_lines,
            "code_churn": churn,

            "net_lines_per_commit": round(
                net_lines / commits,
                2
            ) if commits else 0,

            "additions_per_commit": round(
                additions / commits,
                2
            ) if commits else 0,

            "deletions_per_commit": round(
                deletions / commits,
                2
            ) if commits else 0,

            "churn_per_commit": round(
                churn / commits,
                2
            ) if commits else 0,
        }

    return result


def calculate_activity_bursts(commits):

    buckets = defaultdict(int)

    for commit in commits:

        dt = commit["datetime"]

        minute_bucket = (dt.minute // 5) * 5

        bucket = dt.replace(
            minute=minute_bucket,
            second=0,
            microsecond=0,
        )

        buckets[bucket] += 1

    if not buckets:
        return {
            "period_days": ACTIVITY_DAYS,
            "bucket_minutes": 5,
            "total_buckets": 0,
            "active_buckets": 0,
            "max_commits_in_5min": 0,
            "average_commits_per_active_bucket": 0,
            "top_bursts": [],
        }

    active_counts = list(buckets.values())

    top_bursts = sorted(
        buckets.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]

    return {
        "period_days": ACTIVITY_DAYS,
        "bucket_minutes": 5,
        "total_buckets": int(
            ACTIVITY_DAYS * 24 * 60 / 5
        ),
        "active_buckets": len(buckets),
        "max_commits_in_5min": max(
            active_counts
        ),
        "average_commits_per_active_bucket": round(
            sum(active_counts) / len(active_counts),
            2
        ),
        "top_bursts": [
            {
                "timestamp": bucket.isoformat(),
                "commits": count,
            }
            for bucket, count in top_bursts
        ],
    }




# ------------------------------------------------------------------
# 2. Recent commit activity dataset
#
# This single dataset powers:
#   - hourly activity
#   - weekday × hour heatmap
#   - weekly top-3 commits
#   - 5-minute activity bursts
#   - repository commit concentration
# ------------------------------------------------------------------

from datetime import timedelta
from zoneinfo import ZoneInfo

LOCAL_TIMEZONE = ZoneInfo("Asia/Kolkata")
ACTIVITY_DAYS = 90


def fetch_recent_commits():
    """
    Fetch the user's publicly searchable commits from the last 90 days.

    Returns individual commit records so multiple analytics can be
    calculated without making additional GitHub API calls.
    """

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=ACTIVITY_DAYS)

    commits = []
    search_requests = 0

    window_start = start

    while window_start < now:

        window_end = min(
            window_start + timedelta(days=7),
            now
        )

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

                local_dt = dt.astimezone(LOCAL_TIMEZONE)

                repository = (
                    item.get("repository") or {}
                ).get("name")

                commits.append({
                    "sha": item.get("sha"),
                    "repository": repository,
                    "timestamp_utc": timestamp,
                    "timestamp_ist": local_dt.isoformat(),
                    "datetime": local_dt,
                    "date": local_dt.date().isoformat(),
                    "weekday": WEEKDAY_NAMES[local_dt.weekday()],
                    "hour": local_dt.hour,
                    "minute": local_dt.minute,
                    "message": (
                        commit.get("message") or ""
                    ).splitlines()[0][:160],
                    "url": item.get("html_url"),
                })

            if len(items) < 100:
                break

            page += 1
            time.sleep(0.2)

        window_start = window_end

    # Search windows can overlap on their boundary dates.
    # Deduplicate by SHA.
    unique = {}

    for commit in commits:
        if commit["sha"]:
            unique[commit["sha"]] = commit

    commits = list(unique.values())
    commits.sort(key=lambda x: x["datetime"])

    return {
        "commits": commits,
        "commits_sampled": len(commits),
        "search_requests": search_requests,
        "period_days": ACTIVITY_DAYS,
        "timezone": "Asia/Kolkata",
        "timezone_label": "IST (UTC+05:30)",
        "source": "GitHub Commit Search API",
    }


def build_activity_heatmap(commits):
    """
    Build weekday × hour commit activity matrix.
    """

    heatmap = {
        day: {
            f"{hour:02d}": 0
            for hour in range(24)
        }
        for day in WEEKDAY_NAMES
    }

    for commit in commits:
        day = commit["weekday"]
        hour = f"{commit['hour']:02d}"
        heatmap[day][hour] += 1

    return {
        "timezone": "Asia/Kolkata",
        "period_days": ACTIVITY_DAYS,
        "metric": "commits",
        "days": WEEKDAY_NAMES,
        "hours": [f"{h:02d}" for h in range(24)],
        "matrix": heatmap,
    }









# ---------------------
# ---------------------------------------------
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

    print("INFO: fetching recent commit activity...")
    activity = fetch_recent_commits()

    commits = activity["commits"]

    print("INFO: calculating activity heatmap...")
    heatmap = build_activity_heatmap(commits)

    print("INFO: calculating activity streak...")
    streak = calculate_streak_metrics(
        contrib["daily_contributions"]
    )

    print("INFO: calculating activity acceleration...")
    acceleration = calculate_activity_acceleration(
        contrib["daily_contributions"]
    )

    print("INFO: calculating repository concentration...")
    concentration = calculate_repository_concentration(
        commits
    )

    print("INFO: listing owned repos...")
    repos = fetch_repos()

    print(
        f"INFO: found {len(repos)} owned repos, "
        "fetching lines-of-code statistics..."
    )

    loc = fetch_lines_of_code(repos)

    print("INFO: calculating code churn...")
    churn = calculate_code_churn(loc)

    print("INFO: calculating repository efficiency...")
    repo_efficiency = calculate_repo_efficiency(
        loc["per_repo"]
    )

    print("INFO: calculating top commits per week...")
    top_commits = calculate_top_commits_per_week(
        commits
    )

    print("INFO: calculating 5-minute activity bursts...")
    bursts = calculate_activity_bursts(
        commits
    )

    # Remove internal daily data from final JSON if desired.
    daily_contributions = contrib.pop(
        "daily_contributions",
        {}
    )

    stats = {
        "username": GITHUB_USERNAME,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        # Existing metrics
        **contrib,
        **{
            "hourly_commit_counts": {
                str(h): sum(
                    1
                    for c in commits
                    if c["hour"] == h
                )
                for h in range(24)
            },
            "hourly_timezone": "Asia/Kolkata",
            "hourly_timezone_label": "IST (UTC+05:30)",
            "hourly_period_days": ACTIVITY_DAYS,
            "hourly_source": "GitHub Commit Search API",
            "commits_sampled": len(commits),
        },
        **loc,

        # New metrics
        "activity_heatmap": heatmap,
        "activity_streak": streak,
        "activity_acceleration": acceleration,
        "repository_concentration": concentration,
        "code_churn": churn,
        "repository_efficiency": repo_efficiency,
        "top_3_commits_per_week": top_commits,
        "activity_burst_5min": bursts,
    }

    os.makedirs(
        os.path.dirname(OUT_PATH) or ".",
        exist_ok=True
    )

    with open(
        OUT_PATH,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            stats,
            f,
            indent=2,
            default=str
        )

    print(f"\nINFO: wrote {OUT_PATH}")
    print(
        f"  total contributions : "
        f"{stats['total_contributions']}"
    )
    print(
        f"  avg / day            : "
        f"{stats['avg_per_day']}"
    )
    print(
        f"  avg / week           : "
        f"{stats['avg_per_week']}"
    )
    print(
        f"  total lines added    : "
        f"{stats['total_additions']}"
    )
    print(
        f"  total lines deleted  : "
        f"{stats['total_deletions']}"
    )
    print(
        f"  commits sampled      : "
        f"{len(commits)}"
    )
    print(
        f"  longest streak       : "
        f"{streak['longest_streak']}"
    )
    print(
        f"  current streak       : "
        f"{streak['current_streak']}"
    )
    print(
        f"  repository HHI       : "
        f"{concentration['hhi']}"
    )
    print(
        f"  max 5-min burst      : "
        f"{bursts['max_commits_in_5min']}"
    )


if __name__ == "__main__":
    main()
