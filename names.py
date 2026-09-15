"""
The one editable place for display names: owner names and team names.

Both are plain display labels. Nothing scores off them -- a rename can never
change a standing, a point total or a matchup result. They are denormalized
onto the silver and gold tables, though, so after editing this file run:

    python apply_names.py

which rewrites the names in place and then rebuilds silver and gold. That is a
few seconds of local work; it does NOT re-fetch anything from ESPN and does NOT
re-deal the roster, so every owner keeps exactly the teams they already had.

Two lists
---------
OWNER_NAMES
    One entry per member, in roster order (member 1 first). The count must
    match the number of members in the database -- this league is 8 owners.

TEAM_NAMES
    Optional overrides, keyed by (league, ESPN team id). A team with no entry
    keeps whatever name it already has, so this can start empty and grow.
    Uncomment any line below and edit the right-hand side to rename that team.

    Keying on the ESPN id rather than on the name is deliberate: the id is
    stable, so a rename here survives an ESPN name change instead of silently
    failing to match.

    To undo a rename, set the override back to the ESPN name in the comment --
    do NOT just re-comment the line. Absence means "leave this team alone", not
    "go back to the ESPN name", so re-commenting leaves the last override in
    place. This is the one sharp edge in this file.

    The full current roster is listed below, commented out, so you can see what
    each id refers to. Run `python apply_names.py --list` to reprint it if the
    roster changes.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# Owner names -- edit these. One per member, in roster order.
# --------------------------------------------------------------------------
OWNER_NAMES: list[str] = [
    "Hallies Team",
    "Grants Team",
    "Tofus Riders Encorporated",
    "Ivermectin Users",
    "All State All Stars",
    "0.0% Confidence",
    "Water World 2",
    "Fun Hang Bad Guy",
]

# --------------------------------------------------------------------------
# Team name overrides -- uncomment a line and edit the name on the right.
# Anything left commented keeps its ESPN name.
# --------------------------------------------------------------------------
TEAM_NAMES: dict[tuple[str, str], str] = {
    # -- MLB --
    # ("MLB", "15"): "Braves",               # ESPN: Atlanta Braves
    # ("MLB", "2"): "Red Sox",               # ESPN: Boston Red Sox
    # ("MLB", "16"): "Cubs",                 # ESPN: Chicago Cubs
    # ("MLB", "19"): "Dodgers",              # ESPN: Los Angeles Dodgers
    # ("MLB", "8"): "Brewers",               # ESPN: Milwaukee Brewers
    # ("MLB", "10"): "Yankees",              # ESPN: New York Yankees
    # ("MLB", "22"): "Phillies",             # ESPN: Philadelphia Phillies
    # ("MLB", "30"): "Rays",                 # ESPN: Tampa Bay Rays
    # -- MLS --
    # ("MLS", "185"): "FC Dallas",           # ESPN: FC Dallas
    # ("MLS", "6077"): "Dynamo",             # ESPN: Houston Dynamo FC
    # ("MLS", "20232"): "Miami",             # ESPN: Inter Miami CF
    # ("MLS", "18986"): "Nashville",         # ESPN: Nashville SC
    # ("MLS", "189"): "Revs",                # ESPN: New England Revolution
    # ("MLS", "191"): "Quakes",              # ESPN: San Jose Earthquakes
    # ("MLS", "21812"): "St. Louis",         # ESPN: St. Louis CITY SC
    # ("MLS", "9727"): "Whitecaps",          # ESPN: Vancouver Whitecaps
    # -- NBA --
    # ("NBA", "2"): "Celtics",               # ESPN: Boston Celtics
    # ("NBA", "5"): "Cavs",                  # ESPN: Cleveland Cavaliers
    # ("NBA", "7"): "Nuggets",               # ESPN: Denver Nuggets
    # ("NBA", "8"): "Pistons",               # ESPN: Detroit Pistons
    # ("NBA", "13"): "Lakers",               # ESPN: Los Angeles Lakers
    # ("NBA", "18"): "Knicks",               # ESPN: New York Knicks
    # ("NBA", "25"): "Thunder",              # ESPN: Oklahoma City Thunder
    # ("NBA", "24"): "Spurs",                # ESPN: San Antonio Spurs
    # -- NCAAB --
    # ("NCAAB", "12"): "Arizona",            # ESPN: Arizona
    # ("NCAAB", "150"): "Duke",              # ESPN: Duke
    # ("NCAAB", "248"): "Houston",           # ESPN: Houston
    # ("NCAAB", "356"): "Illinois",          # ESPN: Illinois
    # ("NCAAB", "66"): "Iowa State",         # ESPN: Iowa State
    # ("NCAAB", "130"): "Michigan",          # ESPN: Michigan
    # ("NCAAB", "2509"): "Purdue",           # ESPN: Purdue
    # ("NCAAB", "41"): "UConn",              # ESPN: UConn
    # -- NCAAF --
    # ("NCAAF", "61"): "Georgia",            # ESPN: Georgia
    # ("NCAAF", "84"): "Indiana",            # ESPN: Indiana
    # ("NCAAF", "99"): "LSU",                # ESPN: LSU
    # ("NCAAF", "2390"): "Miami",            # ESPN: Miami
    # ("NCAAF", "87"): "Notre Dame",         # ESPN: Notre Dame
    # ("NCAAF", "194"): "Ohio State",        # ESPN: Ohio State
    # ("NCAAF", "145"): "Ole Miss",          # ESPN: Ole Miss
    # ("NCAAF", "251"): "Texas",             # ESPN: Texas
    # -- NFL --
    # ("NFL", "2"): "Bills",                 # ESPN: Buffalo Bills
    # ("NFL", "7"): "Broncos",               # ESPN: Denver Broncos
    # ("NFL", "34"): "Texans",               # ESPN: Houston Texans
    # ("NFL", "30"): "Jaguars",              # ESPN: Jacksonville Jaguars
    # ("NFL", "14"): "Rams",                 # ESPN: Los Angeles Rams
    # ("NFL", "17"): "Patriots",             # ESPN: New England Patriots
    # ("NFL", "25"): "49ers",                # ESPN: San Francisco 49ers
    # ("NFL", "26"): "Seahawks",             # ESPN: Seattle Seahawks
    # -- NHL --
    # ("NHL", "1"): "Bruins",                # ESPN: Boston Bruins
    # ("NHL", "2"): "Sabres",                # ESPN: Buffalo Sabres
    # ("NHL", "7"): "Hurricanes",            # ESPN: Carolina Hurricanes
    # ("NHL", "17"): "Avalanche",            # ESPN: Colorado Avalanche
    # ("NHL", "9"): "Stars",                 # ESPN: Dallas Stars
    # ("NHL", "30"): "Wild",                 # ESPN: Minnesota Wild
    # ("NHL", "10"): "Canadiens",            # ESPN: Montreal Canadiens
    # ("NHL", "20"): "Lightning",            # ESPN: Tampa Bay Lightning
}


def team_name_override(league_key: str, espn_team_id: str) -> str | None:
    """The configured name for one team, or None to keep the ESPN name."""
    return TEAM_NAMES.get((league_key, espn_team_id))
