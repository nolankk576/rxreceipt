"""Small shared Streamlit helpers: CSS, friendly states, footer."""
from __future__ import annotations

import html
import logging
from contextlib import contextmanager
from pathlib import Path

import streamlit as st

CSS = Path(__file__).resolve().parents[1] / "assets" / "style.css"
log = logging.getLogger("rxreceipt")


def load_css() -> None:
    st.html(f"<style>{CSS.read_text()}</style>")


@contextmanager
def friendly_errors(what: str = "this section"):
    """Show a plain message instead of a stack trace; the details go to the server log."""
    try:
        yield
    except Exception:  # noqa: BLE001 - last line of defence for visitors
        log.exception("error in %s", what)
        st.error(f"Sorry, something went wrong in {what}. Try again, or try a different drug name.",
                 icon=":material/sentiment_dissatisfied:")


def empty_state(icon: str, title: str, body: str) -> None:
    st.html(f'<div class="rx-empty"><div class="big">{icon}</div><b>{html.escape(title)}</b>'
            f'<div class="rx-small">{html.escape(body)}</div></div>')


def data_missing() -> None:
    empty_state("🧾", "Price data isn't loaded yet",
                "The app reads data/nadac_latest.parquet. Run `python scripts/refresh_nadac.py` "
                "(or the 'Refresh NADAC data' GitHub Action) to create it.")


def footer(meta: dict) -> None:
    as_of = meta.get("as_of_date", "unknown date")
    st.divider()
    st.markdown(
        f"""
**Data sources**

- **NADAC** (National Average Drug Acquisition Cost), Centers for Medicare & Medicaid Services, via
  [data.medicaid.gov](https://data.medicaid.gov/). Prices as of **{as_of}**. Refreshed weekly.
- **RxNorm**, U.S. National Library of Medicine, via the [RxNav API](https://lhncbc.nlm.nih.gov/RxNav/APIs/),
  used to match what you type to drug products. Looked up live, cached for 7 days.

**What NADAC is, in plain language:** the average price retail pharmacies pay wholesalers and
manufacturers for a drug, taken from a monthly CMS survey of pharmacy invoices. It is *not* net of
manufacturer rebates or other discounts, and it is *not* what a patient pays.

**Disclaimer:** RxReceipt is educational. It is not medical, financial or legal advice. Prices are
estimates. Don't stop or change a medication without talking to your prescriber or pharmacist.
RxReceipt isn't affiliated with any pharmacy, insurer or drug company.

**Privacy:** nothing you type is stored. Drug names you search are sent to the NLM RxNav API to
find matching products; nothing else leaves the app.
"""
    )
