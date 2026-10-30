import pytest
import streamlit as st


@pytest.fixture(autouse=True)
def clear_result_cache():
    # st.cache_data lives in this process, so it would otherwise carry results between tests.
    st.cache_data.clear()
    yield
    st.cache_data.clear()
