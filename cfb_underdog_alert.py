import os
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"


def get_with_retries(url, attempts=3, delay_seconds=3):
    """Retry a couple of times in case the endpoint hiccups under load."""
    last_resp = None
    for attempt in range(1, attempts + 1):
        resp = requests.get(url)
        if resp.status_code == 200:
            return resp
        last_resp = resp
        print(f"Attempt {attempt}/{attempts} failed: {resp.status_code}")
        if attempt < attempts:
            time.sleep(delay_seconds)
    return last_resp


def main():
    now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    weekday = now_pt.weekday()  # Monday=0 ... Saturday=5, Sunday=6
    hour = now_pt.hour

    in_window = (
        weekday == 5  # Saturday, any hour
        or (weekday == 4 and hour >= 18)  # Friday night, 6pm+
        or (weekday == 6 and hour < 5)  # early Sunday morning (late OT games)
    )
    if not in_window:
        print(f"Outside Pacific game window ({now_pt}), skipping.")
        return

    resp = get_with_retries(SCOREBOARD_URL)
    if resp is None or resp.status_code != 200:
        print(f"Scoreboard request failed: {resp.status_code if resp else 'no response'}")
        return

    data = resp.json()
    events = data.get("events", [])
    alerts_sent = []

    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        comp = competitions[0]

        status = comp.get("status", {})
        state = status.get("type", {}).get("state")  # "pre", "in", "post"
        if state != "in":
            continue
        period = status.get("period", 0)
        if period < 4:
            continue
        clock = status.get("displayClock", "")

        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        home_pts = int(home.get("score") or 0)
        away_pts = int(away.get("score") or 0)
        if home_pts == away_pts:
            continue

        # ESPN uses 99 (or missing) to mean "unranked"
        home_rank = home.get("curatedRank", {}).get("current", 99) or 99
        away_rank = away.get("curatedRank", {}).get("current", 99) or 99

        underdog = favorite = None
        if home_pts > away_pts and home_rank > away_rank:
            underdog, favorite = home, away
        elif away_pts > home_pts and away_rank > home_rank:
            underdog, favorite = away, home
        if underdog is None:
            continue

        underdog_name = underdog["team"]["displayName"]
        favorite_name = favorite["team"]["displayName"]
        underdog_rank = underdog.get("curatedRank", {}).get("current", 99) or 99
        favorite_rank = favorite.get("curatedRank", {}).get("current", 99) or 99
        underdog_label = f"#{underdog_rank} {underdog_name}" if underdog_rank < 99 else f"Unranked {underdog_name}"
        favorite_label = f"#{favorite_rank} {favorite_name}" if favorite_rank < 99 else f"Unranked {favorite_name}"
        underdog_pts = home_pts if underdog is home else away_pts
        favorite_pts = away_pts if underdog is home else home_pts

        message = (
            f"\U0001F6A8 **{underdog_label}** ({underdog_pts}) is leading "
            f"**{favorite_label}** ({favorite_pts}) in Q{period}, {clock} left!"
        )

        requests.post(DISCORD_WEBHOOK_URL, json={"content": message})
        alerts_sent.append(message)

    print(f"Games checked: {len(events)}. Alerts sent: {len(alerts_sent)}")


if __name__ == "__main__":
    main()
