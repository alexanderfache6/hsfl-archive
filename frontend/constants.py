"""Shared constants used across multiple page modules."""

# Standard upper-right, in-figure legend styling used by charts throughout
# the app (Plotly `layout.legend`).
CHART_LEGEND_TOP_RIGHT = {
    "x": 1,
    "y": 1,
    "xanchor": "right",
    "yanchor": "top",
    "bgcolor": "rgba(255,255,255,0.5)",
    "bordercolor": "#888888",
    "borderwidth": 1,
}

SCATTER_PLOT_MARKER_SIZE = 8

# score | info | button - top-3 record-cell row layout shared by the
# History tab's all-time records and the Seasons tab's per-season stats.
RECORD_ROW_COLUMN_RATIOS = [1.5, 4, 2]
