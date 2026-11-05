"""The Churnscope palette. App colours live in .streamlit/config.toml (one block per OS mode);
these constants mirror them for tests, and hold the chart colours shared by both modes.

Chart colours were checked with a colour-blindness validator on the light background, the dark
background and the dark card colour: blue and red stay apart for every type of colour blindness.
"""

LIGHT = {
    "background": "#fcfcfb",
    "surface": "#f3f4f6",
    "border": "#e2e4e8",
    "text": "#0b0b0b",
    "primary": "#2a78d6",
}
DARK = {
    "background": "#0f1419",
    "surface": "#161c25",
    "border": "#2a3340",
    "text": "#e8eaed",
    "primary": "#3987e5",
}

# Plotly figures cannot tell which mode the viewer is in, so these work on both backgrounds.
SERIES = "#3987e5"  # every single-series chart
AT_RISK = "#e34948"  # churn bins at or above the threshold; always named in a legend
INCOMPLETE = "#8c8b86"  # retention cells whose period has not finished
SEQUENTIAL = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")

TRANSPARENT = "rgba(0,0,0,0)"
LAYOUT = {
    "paper_bgcolor": TRANSPARENT,  # the chart sits on the page or card colour
    "plot_bgcolor": TRANSPARENT,
    "barcornerradius": 4,
    "bargap": 0.25,
    "hoverlabel": {"bgcolor": "#161c25", "bordercolor": "#2a3340", "font": {"color": "#e8eaed"}},
    "margin": {"t": 48, "b": 40},
}
