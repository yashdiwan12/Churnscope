from functools import partial

import streamlit as st

import dataset
import gate
from views import churn, engagement, funnel, overview, retention, upload

# (view module, title, url_path). Adding a page is one line here.
PAGES = [
    (overview, "Overview", "overview"),
    (funnel, "Funnel", "funnel"),
    (retention, "Retention", "retention"),
    (engagement, "Engagement", "engagement"),
    (churn, "Churn Risk", "churn-risk"),
    (upload, "Data & Uploads", "upload"),
]

st.set_page_config(page_title="Churnscope", layout="wide")
st.markdown("<style>footer {visibility: hidden;}</style>", unsafe_allow_html=True)
st.title(":material/insights: Churnscope")
st.caption("Product analytics and churn intelligence")
# Pages are built only after the gate returns, so none is reachable without a session.
api, me = gate.require_session()
gate.signed_in_sidebar(me)
ctx = dataset.select(api, me)
st.info(dataset.banner_text(ctx))
page = st.navigation(
    [
        st.Page(partial(view.render, api, ctx), title=title, url_path=url_path)
        for view, title, url_path in PAGES
    ]
)
page.run()
