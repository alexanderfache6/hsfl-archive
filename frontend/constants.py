"""Shared constants used across multiple page modules."""

# for consistent chart legend attributes
CHART_LEGEND_INSIDE_TOP_RIGHT = {
    "x": 1,
    "y": 1,
    "xanchor": "right",
    "yanchor": "top",
    "bgcolor": "rgba(255,255,255,0.5)",
    "bordercolor": "#888888",
    "borderwidth": 1,
}

# for a legend placed OUTSIDE the plot area, to its right - pair with a
# wider right margin (e.g. margin={"r": 150, ...}) so it isn't clipped.
CHART_LEGEND_OUTSIDE_RIGHT = {
    "x": 1.02,
    "y": 1,
    "xanchor": "left",
    "yanchor": "top",
    "bgcolor": "rgba(255,255,255,0.5)",
    "bordercolor": "#888888",
    "borderwidth": 1,
}

# for consistent scatter plot marker size
SCATTER_PLOT_MARKER_SIZE = 8

# for consistent row record column size
RECORD_ROW_COLUMN_RATIOS = [1.5, 4, 2]


# DEF entries carry an empty "nfl_team" in the archived data - it was
# never captured during parsing (only individual players' teams were),
# so this display-only lookup fills it back in from the DEF's own
# player_name (e.g. "49ers") rather than requiring a full re-parse of
# every season just for this one field.
NFL_TEAM_ABBREVIATIONS = {
    "49ers":"SF",
    "Bears": "CHI",
    "Bengals": "CIN",
    "Bills": "BUF",
    "Broncos": "DEN",
    "Browns": "CLE",
    "Buccaneers": "TB",
    "Cardinals": "ARI",
    "Chargers": "LAC",
    "Chiefs": "KC",
    "Colts": "IND",
    "Commanders": "WAS",
    "Cowboys": "DAL",
    "Dolphins": "MIA",
    "Eagles": "PHI",
    "Falcons": "ATL",
    "Giants": "NYG",
    "Jaguars": "JAX",
    "Jets": "NYJ",
    "Lions": "DET",
    "Packers": "GB",
    "Panthers": "CAR",
    "Patriots": "NE",
    "Raiders": "LV",
    "Rams": "LAR",
    "Ravens": "BAL",
    "Redskins": "WAS",
    "Saints": "NO",
    "Seahawks": "SEA",
    "Steelers": "PIT",
    "Texans": "HOU",
    "Titans": "TEN",
    "Vikings": "MIN",
}

# order of positions on a bench roster
BENCH_POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"]


MATCHUP_TYPE_OPTIONS = ["all", "regular", "championship", "consolation"]
MATCHUP_TYPE_LABELS = {
    "all": "All",
    "regular": "Regular Season",
    "championship": "Championship Bracket",
    "consolation": "Consolation Bracket",
}


ORDINAL_WORDS = [
    "zeroth", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
    "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth",
]