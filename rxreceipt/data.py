"""Load the pre-built data files. The app never calls CMS at runtime."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from rxreceipt import search as _search

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NADAC_PATH = DATA / "nadac_latest.parquet"
NADAC_META = DATA / "nadac_meta.json"
WEEK = 7 * 24 * 3600


@st.cache_data(show_spinner=False)
def load_meta(path: str = str(NADAC_META)) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


@st.cache_data(show_spinner=False)
def load_products(path: str = str(NADAC_PATH)) -> pd.DataFrame | None:
    """NADAC grouped into products. None if the data file is missing or unreadable."""
    try:
        nadac = pd.read_parquet(path)
    except Exception:
        return None
    return _search.build_products(nadac)


@st.cache_data(ttl=WEEK, show_spinner=False, max_entries=5000)
def rxnav_get_json(url: str) -> dict | None:
    """Cached RxNav GET. Failures (None) are not worth caching for a week, so we
    raise to skip the cache and let the caller see None."""
    data = _search.http_get_json(url)
    if data is None:
        raise _NoCache
    return data


class _NoCache(Exception):
    """Raised inside a cached function to return a value without caching it."""

    def __init__(self, value=None):
        self.value = value


def cached_rxnav_get(url: str) -> dict | None:
    try:
        return rxnav_get_json(url)
    except _NoCache:
        return None


@st.cache_data(ttl=WEEK, show_spinner=False, max_entries=500)
def _search_cached(query: str, _products: pd.DataFrame, data_version: str):
    rx = _search.RxNorm(cached_rxnav_get)
    result = _search.search(query, _products, rx)
    if not result.rxnorm_ok:  # RxNorm hiccup: use the fuzzy result now, retry next time
        raise _NoCache(result)
    return result


def search(query: str, products: pd.DataFrame, data_version: str) -> _search.SearchResult:
    """Search with a 7-day cache. `data_version` busts it when the NADAC file changes."""
    try:
        return _search_cached(query.strip().lower(), products, data_version)
    except _NoCache as e:
        return e.value
