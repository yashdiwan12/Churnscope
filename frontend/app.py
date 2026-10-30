from functools import partial

import streamlit as st

import gate
from views import funnel, overview, retention

BANNER = "Demo data: synthetic events from a seeded generator, not real customers."

# (view module, title, url_path). Adding a page is one line here.
PAGES = [
    (overview, "Overview", "overview"),
    (funnel, "Funnel", "funnel"),
    (retention, "Retention", "retention"),
]

st.set_page_config(page_title="Churnscope", layout="wide")
st.title("Churnscope")
st.caption("Product analytics and churn intelligence")
st.info(BANNER)

# Pages are built only after the gate returns, so none is reachable without a session.
api, me = gate.require_session()
gate.signed_in_sidebar(me)
page = st.navigation(
    [
        st.Page(partial(view.render, api), title=title, url_path=url_path)
        for view, title, url_path in PAGES
    ]
)
page.run()
