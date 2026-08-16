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
