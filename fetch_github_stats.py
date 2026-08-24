#!/usr/bin/env python3

"""
fetch_github_stats.py

Pulls contribution + commit activity + lines-of-code statistics
from GitHub and writes them to assets/github_stats.json.

gif_script.py reads that file (if present) and renders a
"$ contrib_stats" section in the terminal GIF; if the file is
missing, that section is skipped and the GIF still builds normally.

Run this BEFORE gif_script.py:

    export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
    export GITHUB_USERNAME=yourusername

    python fetch_github_stats.py
    python gif_script.py


------------------------------------------------------------------------
WHY A PERSONAL ACCESS TOKEN (PAT) IS REQUIRED
------------------------------------------------------------------------

- The daily contribution calendar is exposed via GitHub's GraphQL API
  and requires authentication.

- Lines-of-code statistics come from the REST
  "stats/contributors" endpoint.

- Commit activity comes from the GitHub Commit Search API.

- GitHub does not provide a single endpoint containing complete
  historical commit timestamps for all time, so the hourly,
  heatmap, burst and weekly-commit analytics are based on the
  recent searchable commit window configured below.


------------------------------------------------------------------------
WHICH TOKEN / SCOPES
------------------------------------------------------------------------

Classic PAT:

    https://github.com/settings/tokens

    - read:user -> required for the contribution calendar
    - repo      -> needed if private repositories should be included

A fine-grained PAT also works with appropriate read-only access to
Contents + Metadata and profile/account access.

NEVER hard-code the token in this file or commit it.

Always provide it through:

    GITHUB_TOKEN
"""

import os
import sys
import json
import time

import requests

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME")

OUT_PATH = "assets/github_stats.json"

GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"

LOCAL_TIMEZONE = ZoneInfo("Asia/Kolkata")

WEEKDAY_NAMES = [
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
]

ACTIVITY_DAYS = 90


# ----------------------------------------------------------------------
# Authentication
# ----------------------------------------------------------------------

def _require_auth():
    if not GITHUB_TOKEN or not GITHUB_USERNAME:
        print(
            "ERROR: GITHUB_TOKEN and GITHUB_USERNAME environment "
            "variables are required.\n"
            "  export GITHUB_TOKEN=ghp_xxx...\n"
            "  export GITHUB_USERNAME=yourusername",
            file=sys.stderr,
        )
        sys.exit(1)


def _headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


# ----------------------------------------------------------------------
# 1. Contribution Calendar
# ----------------------------------------------------------------------

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
    """
    Fetch the trailing contribution calendar from GitHub.

    The individual daily contribution counts are retained internally
    so streak and acceleration metrics can be calculated accurately.
    """

    resp = requests.post(
        GRAPHQL_URL,
        json={
            "query": CONTRIB_QUERY,
            "variables": {
                "login": GITHUB_USERNAME
            },
        },
        headers=_headers(),
        timeout=30,
    )

    resp.raise_for_status()

    data = resp.json()

    if "errors" in data:
        raise RuntimeError(
            f"GraphQL error: {data['errors']}"
        )

    calendar = (
        data["data"]["user"]
        ["contributionsCollection"]
        ["contributionCalendar"]
    )

    total = calendar["totalContributions"]
    weeks = calendar["weeks"]

    by_weekday = defaultdict(int)

    days_with_data = 0

    daily_contributions = {}

    for week in weeks:
        for day in week["contributionDays"]:

            date_string = day["date"]
            count = day["contributionCount"]

            date = datetime.fromisoformat(
                date_string
            ).replace(tzinfo=timezone.utc)

            weekday = WEEKDAY_NAMES[
                date.weekday()
            ]

            by_weekday[weekday] += count
            days_with_data += 1

            daily_contributions[
                date_string
            ] = count

    num_weeks = len(weeks) or 1

    avg_per_day = (
        total / days_with_data
        if days_with_data
        else 0
    )

    avg_per_week = total / num_weeks

    avg_by_weekday = {
        day: round(
            by_weekday.get(day, 0)
            / max(num_weeks, 1),
            2,
        )
        for day in WEEKDAY_NAMES
    }

    return {
        "total_contributions": total,

        "avg_per_day": round(
            avg_per_day,
            2,
        ),

        "avg_per_week": round(
            avg_per_week,
            2,
        ),

        "total_per_weekday": dict(
            by_weekday
        ),

        "avg_per_weekday": avg_by_weekday,

        "weeks_covered": num_weeks,

        # Used internally for streak / acceleration.
        "daily_contributions": daily_contributions,
    }


# ----------------------------------------------------------------------
# 2. Activity Streak
# ----------------------------------------------------------------------

def calculate_streak_metrics(
    daily_contributions,
    period_days=90,
):
    """
    Calculate activity streak metrics over the trailing period.

    Active day:
        At least one GitHub contribution.

    The streak is based on GitHub contribution activity rather
    than commits alone.
    """

    today = datetime.now(
        timezone.utc
    ).date()

    cutoff = today - timedelta(
        days=period_days - 1
    )

    filtered = {
        date_string: count
        for date_string, count
        in daily_contributions.items()
        if cutoff
        <= datetime.fromisoformat(
            date_string
        ).date()
        <= today
    }

    if not filtered:
        return {
            "period_days": period_days,
            "active_days": 0,
            "inactive_days": period_days,
            "longest_streak": 0,
            "current_streak": 0,
            "average_active_day_contributions": 0,
        }

    dates = sorted(filtered.keys())

    active_days = sum(
        1
        for count in filtered.values()
        if count > 0
    )

    inactive_days = period_days - active_days

    longest_streak = 0
    streak = 0
    previous_date = None

    for date_string in dates:

        date = datetime.fromisoformat(
            date_string
        ).date()

        count = filtered[date_string]

        if count > 0:

            if (
                previous_date is not None
                and date
                == previous_date + timedelta(days=1)
            ):
                streak += 1
            else:
                streak = 1

            longest_streak = max(
                longest_streak,
                streak,
            )

        else:
            streak = 0

        previous_date = date

    current_streak = 0

    for offset in range(period_days):

        date = today - timedelta(
            days=offset
        )

        date_string = date.isoformat()

        if filtered.get(
            date_string,
            0,
        ) > 0:
            current_streak += 1
        else:
            break

    active_counts = [
        count
        for count in filtered.values()
        if count > 0
    ]

    average_active_day_contributions = (
        sum(active_counts)
        / len(active_counts)
        if active_counts
        else 0
    )

    return {
        "period_days": period_days,
        "active_days": active_days,
        "inactive_days": inactive_days,
        "longest_streak": longest_streak,
        "current_streak": current_streak,
        "average_active_day_contributions": round(
            average_active_day_contributions,
            2,
        ),
    }


# ----------------------------------------------------------------------
# 3. Activity Acceleration
# ----------------------------------------------------------------------

def calculate_activity_acceleration(
    daily_contributions,
):
    """
    Calculate average daily contribution activity over:

        30 days
        60 days
        90 days
        180 days
        365 days
    """

    today = datetime.now(
        timezone.utc
    ).date()

    windows = [
        30,
        60,
        90,
        180,
        365,
    ]

    result = {}

    for days in windows:

        cutoff = today - timedelta(
            days=days - 1
        )

        values = []

        for date_string, count in (
            daily_contributions.items()
        ):

            date = datetime.fromisoformat(
                date_string
            ).date()

            if cutoff <= date <= today:
                values.append(count)

        result[
            f"{days}_day_average"
        ] = round(
            sum(values) / days,
            2,
        )

    a30 = result["30_day_average"]
    a90 = result["90_day_average"]
    a180 = result["180_day_average"]
    a365 = result["365_day_average"]

    result["30_vs_90_ratio"] = (
        round(a30 / a90, 3)
        if a90
        else None
    )

    result["90_vs_180_ratio"] = (
        round(a90 / a180, 3)
        if a180
        else None
    )

    result["90_vs_365_ratio"] = (
        round(a90 / a365, 3)
        if a365
        else None
    )

    return result


# ----------------------------------------------------------------------
# 4. Recent Commit Dataset
# ----------------------------------------------------------------------

def fetch_recent_commits():
    """
    Fetch publicly searchable commits from the last 90 days.

    GitHub Search is divided into seven-day windows.

    Commit timestamps are converted to IST.
    """

    now = datetime.now(
        timezone.utc
    )

    start = now - timedelta(
        days=ACTIVITY_DAYS
    )

    commits = []

    search_requests = 0

    window_start = start

    while window_start < now:

        window_end = min(
            window_start + timedelta(days=7),
            now,
        )

        query = (
            f"author:{GITHUB_USERNAME} "
            f"committer-date:"
            f"{window_start.strftime('%Y-%m-%d')}"
            f".."
            f"{window_end.strftime('%Y-%m-%d')}"
        )

        page = 1

        while page <= 500:

            resp = requests.get(
                f"{REST_URL}/search/commits",
                headers=_headers(),
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
                    "WARNING: commit search failed "
                    f"({resp.status_code}): "
                    f"{resp.text[:300]}",
                    file=sys.stderr,
                )

                break

            data = resp.json()

            items = data.get(
                "items",
                [],
            )

            if not items:
                break

            for item in items:

                commit = (
                    item.get("commit")
                    or {}
                )

                committer = (
                    commit.get("committer")
                    or {}
                )

                timestamp = committer.get(
                    "date"
                )

                if not timestamp:
                    continue

                try:

                    dt = datetime.fromisoformat(
                        timestamp.replace(
                            "Z",
                            "+00:00",
                        )
                    )

                except ValueError:
                    continue

                # Enforce the exact 90-day boundary.
                if not (
                    start
                    <= dt
                    <= now
                ):
                    continue

                local_dt = dt.astimezone(
                    LOCAL_TIMEZONE
                )

                repository = (
                    item.get("repository")
                    or {}
                ).get("name")

                message = (
                    commit.get("message")
                    or ""
                ).splitlines()[0][:160]

                commits.append({
                    "sha": item.get("sha"),

                    "repository": repository,

                    "timestamp_utc": timestamp,

                    "timestamp_ist": (
                        local_dt.isoformat()
                    ),

                    "datetime": local_dt,

                    "date": (
                        local_dt.date().isoformat()
                    ),

                    "weekday": (
                        WEEKDAY_NAMES[
                            local_dt.weekday()
                        ]
                    ),

                    "hour": local_dt.hour,

                    "minute": local_dt.minute,

                    "message": message,

                    "url": item.get(
                        "html_url"
                    ),
                })

            if len(items) < 100:
                break

            page += 1

            time.sleep(0.2)

        window_start = window_end

    # Deduplicate commits by SHA.
    unique = {}

    for commit in commits:

        sha = commit.get("sha")

        if sha:
            unique[sha] = commit

    commits = list(
        unique.values()
    )

    commits.sort(
        key=lambda x:
        x["datetime"]
    )

    return {
        "commits": commits,

        "commits_sampled": len(
            commits
        ),

        "search_requests": search_requests,

        "period_days": ACTIVITY_DAYS,

        "period_start_utc": (
            start.isoformat()
        ),

        "period_end_utc": (
            now.isoformat()
        ),

        "period_start_ist": (
            start.astimezone(
                LOCAL_TIMEZONE
            ).isoformat()
        ),

        "period_end_ist": (
            now.astimezone(
                LOCAL_TIMEZONE
            ).isoformat()
        ),

        "timezone": "Asia/Kolkata",

        "timezone_label": (
            "IST (UTC+05:30)"
        ),

        "source": (
            "GitHub Commit Search API"
        ),
    }


# ----------------------------------------------------------------------
# 5. Hourly Activity
# ----------------------------------------------------------------------

def calculate_hourly_activity(commits):
    """
    Calculate total commits and percentage of commits
    for each hour of the day.

    Percentages represent the share of all sampled commits
    that occurred during each hour.

    Example:

        22:00 = 49 commits
        Total = 209 commits

        49 / 209 * 100 = 23.44%
    """

    hourly_counts = {
        f"{hour:02d}": 0
        for hour in range(24)
    }

    for commit in commits:

        hour = commit["hour"]

        hourly_counts[
            f"{hour:02d}"
        ] += 1

    total_commits = sum(
        hourly_counts.values()
    )

    hourly_percentages = {
        hour: round(
            count / total_commits * 100,
            2,
        )
        if total_commits
        else 0
        for hour, count
        in hourly_counts.items()
    }

    if total_commits:

        peak_hour = max(
            hourly_counts,
            key=hourly_counts.get,
        )

        peak_count = hourly_counts[
            peak_hour
        ]

        peak_percentage = (
            hourly_percentages[
                peak_hour
            ]
        )

    else:

        peak_hour = "00"
        peak_count = 0
        peak_percentage = 0

    peak_hour_int = int(
        peak_hour
    )

    if 5 <= peak_hour_int < 12:
        period = "Morning"

    elif 12 <= peak_hour_int < 17:
        period = "Afternoon"

    elif 17 <= peak_hour_int < 21:
        period = "Evening"

    else:
        period = "Night"

    return {
        "hourly_commit_counts": (
            hourly_counts
        ),

        "hourly_commit_percentages": (
            hourly_percentages
        ),

        "hourly_total_commits": (
            total_commits
        ),

        "hourly_timezone": "Asia/Kolkata",

        "hourly_timezone_label": (
            "IST (UTC+05:30)"
        ),

        "hourly_period_days": (
            ACTIVITY_DAYS
        ),

        "hourly_source": (
            "GitHub Commit Search API"
        ),

        "commits_sampled": (
            total_commits
        ),

        "peak_hour": peak_hour_int,

        "peak_hour_label": (
            f"{peak_hour_int:02d}:00–"
            f"{peak_hour_int:02d}:59 IST"
        ),

        "peak_hour_commit_count": (
            peak_count
        ),

        "peak_hour_percentage": (
            peak_percentage
        ),

        "most_active_period": period,
    }


# ----------------------------------------------------------------------
# 6. Activity Heatmap
# ----------------------------------------------------------------------

def build_activity_heatmap(commits):
    """
    Build a weekday × hour commit activity matrix.

    Both raw counts and percentages are returned.

    matrix_counts:
        Number of commits in each weekday/hour bucket.

    matrix_percentages:
        Percentage of all commits represented by each bucket.
    """

    heatmap_counts = {
        day: {
            f"{hour:02d}": 0
            for hour in range(24)
        }
        for day in WEEKDAY_NAMES
    }

    for commit in commits:

        day = commit["weekday"]

        hour = f"{commit['hour']:02d}"

        heatmap_counts[
            day
        ][hour] += 1

    total_commits = sum(
        sum(day.values())
        for day in heatmap_counts.values()
    )

    heatmap_percentages = {
        day: {
            hour: round(
                count / total_commits * 100,
                2,
            )
            if total_commits
            else 0
            for hour, count
            in hours.items()
        }
        for day, hours
        in heatmap_counts.items()
    }

    return {
        "timezone": "Asia/Kolkata",

        "period_days": ACTIVITY_DAYS,

        "metric": "commits",

        "total_commits": (
            total_commits
        ),

        "days": WEEKDAY_NAMES,

        "hours": [
            f"{hour:02d}"
            for hour in range(24)
        ],

        "matrix_counts": (
            heatmap_counts
        ),

        "matrix_percentages": (
            heatmap_percentages
        ),
    }


# ----------------------------------------------------------------------
# 7. Repository Concentration — Herfindahl-style
# ----------------------------------------------------------------------

def calculate_repository_concentration(
    commits,
):
    """
    Calculate repository concentration using commit share.

    HHI = sum(repository_share²)

    HHI:
        1.0 = completely concentrated
        lower values = more diversified

    Effective repositories:
        1 / HHI
    """

    repo_counts = defaultdict(int)

    for commit in commits:

        repo = commit.get(
            "repository"
        )

        if repo:
            repo_counts[repo] += 1

    total = sum(
        repo_counts.values()
    )

    if not total:

        return {
            "metric": (
                "Herfindahl-Hirschman Index"
            ),

            "basis": "commits",

            "period_days": ACTIVITY_DAYS,

            "hhi": 0,

            "effective_repositories": 0,

            "repository_shares": {},

            "repository_commits": {},
        }

    shares = {
        repo: count / total
        for repo, count
        in repo_counts.items()
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
        "metric": (
            "Herfindahl-Hirschman Index"
        ),

        "basis": "commits",

        "period_days": ACTIVITY_DAYS,

        "hhi": round(
            hhi,
            4,
        ),

        "effective_repositories": round(
            effective_repositories,
            2,
        ),

        "repository_shares": {
            repo: round(
                share,
                4,
            )
            for repo, share in sorted(
                shares.items(),
                key=lambda x: x[1],
                reverse=True,
            )
        },

        "repository_commits": dict(
            sorted(
                repo_counts.items(),
                key=lambda x: x[1],
                reverse=True,
            )
        ),
    }


# ----------------------------------------------------------------------
# 8. Repository Listing
# ----------------------------------------------------------------------

def fetch_repos():

    repos = []

    page = 1

    while True:

        resp = requests.get(
            f"{REST_URL}/users/"
            f"{GITHUB_USERNAME}/repos",

            headers=_headers(),

            params={
                "per_page": 100,
                "page": page,
                "type": "owner",
            },

            timeout=30,
        )

        resp.raise_for_status()

        batch = resp.json()

        if not batch:
            break

        repos.extend(
            repo["name"]
            for repo in batch
            if not repo.get("fork")
        )

        page += 1

    return repos


# ----------------------------------------------------------------------
# 9. Lines of Code / Repository Statistics
# ----------------------------------------------------------------------

def fetch_lines_of_code(repos):
    """
    Fetch lifetime repository contributor statistics.

    For each owned, non-fork repository, collect:

        additions
        deletions
        commits
    """

    total_additions = 0
    total_deletions = 0
    total_commits = 0

    per_repo = {}

    for repo in repos:

        url = (
            f"{REST_URL}/repos/"
            f"{GITHUB_USERNAME}/{repo}"
            f"/stats/contributors"
        )

        resp = None

        for _attempt in range(3):

            resp = requests.get(
                url,
                headers=_headers(),
                timeout=30,
            )

            if resp.status_code == 202:

                time.sleep(2)

                continue

            break

        if (
            resp is None
            or resp.status_code != 200
        ):
            continue

        contributors = (
            resp.json()
            or []
        )

        added = 0
        deleted = 0
        commits = 0

        for contributor in contributors:

            author = (
                contributor.get("author")
                or {}
            )

            if author.get("login") != (
                GITHUB_USERNAME
            ):
                continue

            for week in contributor.get(
                "weeks",
                [],
            ):

                added += week.get(
                    "a",
                    0,
                )

                deleted += week.get(
                    "d",
                    0,
                )

                commits += week.get(
                    "c",
                    0,
                )

        if (
            added
            or deleted
            or commits
        ):

            per_repo[repo] = {
                "additions": added,
                "deletions": deleted,
                "commits": commits,
            }

            total_additions += added
            total_deletions += deleted
            total_commits += commits

    return {
        "total_additions": total_additions,

        "total_deletions": total_deletions,

        "total_commits": total_commits,

        "net_lines": (
            total_additions
            - total_deletions
        ),

        "per_repo": per_repo,
    }


# ----------------------------------------------------------------------
# 10. Code Churn
# ----------------------------------------------------------------------

def calculate_code_churn(loc):

    additions = loc[
        "total_additions"
    ]

    deletions = loc[
        "total_deletions"
    ]

    total_churn = (
        additions
        + deletions
    )

    return {
        "scope": "repository_history",

        "additions": additions,

        "deletions": deletions,

        "total_churn": total_churn,

        "net_lines": (
            additions
            - deletions
        ),

        "deletion_ratio": round(
            deletions / additions,
            4,
        )
        if additions
        else 0,

        "deletion_percentage_of_churn": round(
            deletions
            / total_churn
            * 100,
            2,
        )
        if total_churn
        else 0,
    }


# ----------------------------------------------------------------------
# 11. Repository-wise Code Efficiency
# ----------------------------------------------------------------------

def calculate_repo_efficiency(
    per_repo,
):
    """
    Calculate repository-level efficiency metrics.

    Metrics:

        net_lines / commits
        additions / commits
        deletions / commits
        churn / commits
    """

    result = {}

    for repo, data in (
        per_repo.items()
    ):

        additions = data[
            "additions"
        ]

        deletions = data[
            "deletions"
        ]

        commits = data[
            "commits"
        ]

        net_lines = (
            additions
            - deletions
        )

        churn = (
            additions
            + deletions
        )

        result[repo] = {
            "commits": commits,

            "additions": additions,

            "deletions": deletions,

            "net_lines": net_lines,

            "code_churn": churn,

            "net_lines_per_commit": round(
                net_lines / commits,
                2,
            )
            if commits
            else 0,

            "additions_per_commit": round(
                additions / commits,
                2,
            )
            if commits
            else 0,

            "deletions_per_commit": round(
                deletions / commits,
                2,
            )
            if commits
            else 0,

            "churn_per_commit": round(
                churn / commits,
                2,
            )
            if commits
            else 0,
        }

    return result


# ----------------------------------------------------------------------
# 12. Top 3 Commits per Week
# ----------------------------------------------------------------------

def calculate_top_commits_per_week(
    commits,
):
    """
    Return the top 3 commits per ISO week.

    Current ranking:
        chronological
    """

    weekly = defaultdict(list)

    for commit in commits:

        dt = commit[
            "datetime"
        ]

        year, week, _ = (
            dt.isocalendar()
        )

        week_key = (
            f"{year}-W{week:02d}"
        )

        weekly[
            week_key
        ].append(commit)

    result = {}

    for week, week_commits in sorted(
        weekly.items()
    ):

        week_commits = sorted(
            week_commits,
            key=lambda x:
            x["datetime"],
        )

        result[week] = [
            {
                "sha": commit["sha"],

                "repository": (
                    commit["repository"]
                ),

                "timestamp": (
                    commit["timestamp_ist"]
                ),

                "message": (
                    commit["message"]
                ),

                "url": commit["url"],
            }
            for commit
            in week_commits[:3]
        ]

    return {
        "period_days": ACTIVITY_DAYS,

        "metric": (
            "chronological_commits"
        ),

        "top_3_commits_per_week": result,
    }


# ----------------------------------------------------------------------
# 13. 5-minute Activity Bursts
# ----------------------------------------------------------------------

def calculate_activity_bursts(
    commits,
):
    """
    Group commits into five-minute time buckets.
    """

    buckets = defaultdict(int)

    for commit in commits:

        dt = commit[
            "datetime"
        ]

        minute_bucket = (
            dt.minute // 5
        ) * 5

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

    active_counts = list(
        buckets.values()
    )

    top_bursts = sorted(
        buckets.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    return {
        "period_days": ACTIVITY_DAYS,

        "bucket_minutes": 5,

        "total_buckets": int(
            ACTIVITY_DAYS
            * 24
            * 60
            / 5
        ),

        "active_buckets": len(
            buckets
        ),

        "max_commits_in_5min": max(
            active_counts
        ),

        "average_commits_per_active_bucket": round(
            sum(active_counts)
            / len(active_counts),
            2,
        ),

        "top_bursts": [
            {
                "timestamp": (
                    bucket.isoformat()
                ),

                "commits": count,
            }

            for bucket, count
            in top_bursts
        ],
    }


# ----------------------------------------------------------------------
# 14. Main
# ----------------------------------------------------------------------

def main():

    _require_auth()

    # --------------------------------------------------------------
    # Contribution calendar
    # --------------------------------------------------------------

    print(
        "INFO: fetching contribution calendar..."
    )

    contrib = (
        fetch_contribution_calendar()
    )

    # --------------------------------------------------------------
    # Recent commit dataset
    # --------------------------------------------------------------

    print(
        "INFO: fetching recent commit activity..."
    )

    activity = (
        fetch_recent_commits()
    )

    commits = activity[
        "commits"
    ]

    # --------------------------------------------------------------
    # Hourly activity
    # --------------------------------------------------------------

    print(
        "INFO: calculating hourly activity..."
    )

    hourly = (
        calculate_hourly_activity(
            commits
        )
    )

    # --------------------------------------------------------------
    # Activity heatmap
    # --------------------------------------------------------------

    print(
        "INFO: calculating activity heatmap..."
    )

    heatmap = (
        build_activity_heatmap(
            commits
        )
    )

    # --------------------------------------------------------------
    # Activity streak
    # --------------------------------------------------------------

    print(
        "INFO: calculating 90-day activity streak..."
    )

    streak = (
        calculate_streak_metrics(
            contrib[
                "daily_contributions"
            ],
            period_days=90,
        )
    )

    # --------------------------------------------------------------
    # Activity acceleration
    # --------------------------------------------------------------

    print(
        "INFO: calculating activity acceleration..."
    )

    acceleration = (
        calculate_activity_acceleration(
            contrib[
                "daily_contributions"
            ]
        )
    )

    # --------------------------------------------------------------
    # Repository concentration
    # --------------------------------------------------------------

    print(
        "INFO: calculating repository concentration..."
    )

    concentration = (
        calculate_repository_concentration(
            commits
        )
    )

    # --------------------------------------------------------------
    # Repository list
    # --------------------------------------------------------------

    print(
        "INFO: listing owned repositories..."
    )

    repos = fetch_repos()

    print(
        f"INFO: found {len(repos)} owned repos, "
        "fetching lines-of-code statistics..."
    )

    # --------------------------------------------------------------
    # LOC / repository statistics
    # --------------------------------------------------------------

    loc = fetch_lines_of_code(
        repos
    )

    # --------------------------------------------------------------
    # Code churn
    # --------------------------------------------------------------

    print(
        "INFO: calculating code churn..."
    )

    churn = (
        calculate_code_churn(
            loc
        )
    )

    # --------------------------------------------------------------
    # Repository efficiency
    # --------------------------------------------------------------

    print(
        "INFO: calculating repository efficiency..."
    )

    repo_efficiency = (
        calculate_repo_efficiency(
            loc[
                "per_repo"
            ]
        )
    )

    # --------------------------------------------------------------
    # Top commits per week
    # --------------------------------------------------------------

    print(
        "INFO: calculating top commits per week..."
    )

    top_commits = (
        calculate_top_commits_per_week(
            commits
        )
    )

    # --------------------------------------------------------------
    # Five-minute activity bursts
    # --------------------------------------------------------------

    print(
        "INFO: calculating 5-minute activity bursts..."
    )

    bursts = (
        calculate_activity_bursts(
            commits
        )
    )

    # --------------------------------------------------------------
    # Remove internal daily contribution data
    # --------------------------------------------------------------

    contrib.pop(
        "daily_contributions",
        None,
    )

    # --------------------------------------------------------------
    # Final JSON
    # --------------------------------------------------------------

    stats = {
        "username": GITHUB_USERNAME,

        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),

        **contrib,

        **hourly,

        **loc,

        "activity_heatmap": heatmap,

        "activity_streak": streak,

        "activity_acceleration": (
            acceleration
        ),

        "repository_concentration": (
            concentration
        ),

        "code_churn": churn,

        "repository_efficiency": (
            repo_efficiency
        ),

        "top_3_commits_per_week": (
            top_commits
        ),

        "activity_burst_5min": bursts,
    }

    # --------------------------------------------------------------
    # Write JSON
    # --------------------------------------------------------------

    os.makedirs(
        os.path.dirname(
            OUT_PATH
        )
        or ".",
        exist_ok=True,
    )

    with open(
        OUT_PATH,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            stats,
            f,
            indent=2,
            default=str,
        )

    # --------------------------------------------------------------
    # Summary
    # --------------------------------------------------------------

    print(
        f"\nINFO: wrote {OUT_PATH}"
    )

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
        f"  total commits        : "
        f"{stats['total_commits']}"
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

    print(
        f"  peak hour            : "
        f"{hourly['peak_hour_label']}"
    )

    print(
        f"  peak hour commits    : "
        f"{hourly['peak_hour_commit_count']}"
    )

    print(
        f"  peak hour percentage : "
        f"{hourly['peak_hour_percentage']}%"
    )


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

if __name__ == "__main__":
    main()
