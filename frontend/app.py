import os

import httpx
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Churnscope", layout="wide")
st.title("Churnscope")
st.caption("Product analytics and churn intelligence")

try:
    status = httpx.get(f"{API_BASE_URL}/health", timeout=5).json()["status"]
    st.success(f"API status: {status}")
except (httpx.HTTPError, KeyError, ValueError):
    st.error("API unavailable. Start the backend or check API_BASE_URL.")
