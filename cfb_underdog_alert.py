import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

CFBD_API_KEY = os.environ["CFBD_API_KEY"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]


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

    headers = {"Authorization": f"Bearer {CFBD_API_KEY}", "Accept": "application/json"}
    year = now_pt.year

    # 1. Get current AP Top 25 rankings
    rankings_req = requests.get(
        "https://api.collegefootballdata.com/rankings",
        params={"year": year},
        headers=headers,
    )
    if rankings_req.status_code != 200:
        print(f"Rankings request failed ({rankings_req.status_code}): {rankings_req.text}")
        return
    rankings_resp = rankings_req.json()
    if not isinstance(rankings_resp, list):
        print(f"Unexpected rankings response: {rankings_resp}")
        return

    ranked_teams = {}
    if rankings_resp:
        latest_week = rankings_resp[-1]
        for poll in latest_week.get("polls", []):
            if poll.get("poll") == "AP Top 25":
                for entry in poll.get("ranks", []):
                    ranked_teams[entry["school"]] = entry["rank"]

    # 2. Get the live scoreboard
    scoreboard_req = requests.get(
        "https://api.collegefootballdata.com/scoreboard",
        params={"classification": "fbs"},
        headers=headers,
    )
    if scoreboard_req.status_code != 200:
        print(f"Scoreboard request failed ({scoreboard_req.status_code}): {scoreboard_req.text}")
        return
    games = scoreboard_req.json()
    if not isinstance(games, list):
        print(f"Unexpected scoreboard response: {games}")
        return

    alerts_sent = []

    for game in games:
        if game.get("status") != "in_progress":
            continue
        period = game.get("period", 0)
        if period < 4:
            continue

        home = game["homeTeam"]
        away = game["awayTeam"]
        home_pts = home.get("points") or 0
        away_pts = away.get("points") or 0
        if home_pts == away_pts:
            continue  # tied, no leader

        home_rank = ranked_teams.get(home["name"], 999)
        away_rank = ranked_teams.get(away["name"], 999)

        underdog = None
        favorite = None
        if home_pts > away_pts and home_rank > away_rank:
            underdog, favorite = home, away
        elif away_pts > home_pts and away_rank > home_rank:
            underdog, favorite = away, home

        if underdog is None:
            continue

        underdog_rank = ranked_teams.get(underdog["name"])
        favorite_rank = ranked_teams.get(favorite["name"])
        underdog_label = f"#{underdog_rank} {underdog['name']}" if underdog_rank else f"Unranked {underdog['name']}"
        favorite_label = f"#{favorite_rank} {favorite['name']}" if favorite_rank else f"Unranked {favorite['name']}"
        underdog_pts = home_pts if underdog is home else away_pts
        favorite_pts = away_pts if underdog is home else home_pts

        message = (
            f"\U0001F6A8 **{underdog_label}** ({underdog_pts}) is leading "
            f"**{favorite_label}** ({favorite_pts}) in Q{period}, "
            f"{game.get('clock', '')} left!"
        )

        requests.post(DISCORD_WEBHOOK_URL, json={"content": message})
        alerts_sent.append(message)

    print(f"Games checked: {len(games)}. Alerts sent: {len(alerts_sent)}")


if __name__ == "__main__":
    main()
