# ----------------------------------------
# emojis
# ----------------------------------------

EMOJI_FIRST_PLACE = "🏆"
EMOJI_SECOND_PLACE = "🥈"
EMOJI_THIRD_PLACE = "🥉"
EMOJI_LAST_PLACE = "🥞"

EMOJI_NO_FIRST_PLACE = "😭"
EMOJI_NO_SECOND_PLACE = "😢"
EMOJI_NO_THIRD_PLACE = "☹️"

# ----------------------------------------
# chart legends
# ----------------------------------------

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

# ----------------------------------------
# chart markers
# ----------------------------------------

# for consistent scatter plot marker size
SCATTER_PLOT_MARKER_SIZE = 8

# for draft charts' (pages_drafts.py) larger markers
SCATTER_PLOT_DRAFT_MARKER_SIZE = 12

# for the Player Analysis tab's Auction Price line width
CHART_LINE_AUCTION_WIDTH = 8
CHART_LINE_OTHER_WIDTH = 2

# for consistent y-axis tick density (Plotly's own nticks parameter)
MAX_YAXIS_TICKS = 20

# ----------------------------------------
# column size
# ----------------------------------------

# for consistent row record column size
RECORD_ROW_COLUMN_RATIOS = [1.5, 4, 2]

# ----------------------------------------
# nfl
# ----------------------------------------

NFL_TEAM_ABBREVIATIONS = {
    "49ers": "SF",
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

# ----------------------------------------
# roster order
# ----------------------------------------

# order of positions on a bench roster
BENCH_POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"]

# source matplotlib.colormaps["Dark2"].colors
BENCH_POSITION_COLOR = {
    "QB": "#1B9E77",
    "RB": "#D95F02",
    "WR": "#7570B3",
    "TE": "#E7298A",
    "K": "#66A61E",
    "DEF": "#E6AB02",
}

# ----------------------------------------
# drafts
# ----------------------------------------

# ESPN's default per-team auction budget - not itself stored anywhere in
# the archived draft.json data, but every auction season's picks sum to
# (or just under, when a keeper ate part of the budget) this per team,
# confirming it's the actual league setting rather than a guess.
AUCTION_BUDGET = 200  # TODO needs to come from season recap

# ----------------------------------------
# matchups
# ----------------------------------------

MATCHUP_TYPE_OPTIONS = ["all", "regular", "championship", "consolation"]
MATCHUP_TYPE_LABELS = {
    "all": "All",
    "regular": "Regular Season",
    "championship": "Championship Bracket",
    "consolation": "Consolation Bracket",
}

# ----------------------------------------
# strings
# ----------------------------------------

ORDINAL_WORDS = [
    "zeroth",
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
]
