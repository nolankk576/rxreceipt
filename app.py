"""RxReceipt: see what your prescription really costs.

Run locally:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="RxReceipt — what your prescription really costs", page_icon="🧾",
                   layout="centered")

from rxreceipt import ui  # noqa: E402  (after set_page_config)

ui.load_css()

pages = [
    st.Page("app_pages/receipt.py", title="Receipt", icon=":material/receipt_long:", default=True),
    st.Page("app_pages/about.py", title="About the data", icon=":material/info:"),
]
st.navigation(pages, position="top").run()
