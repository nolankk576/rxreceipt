"""Turn what someone types ("Lipitor", "atorvastatin 20mg") into NADAC products.

Path 1 (RxNorm, NLM, no key):
    approximateTerm  -> the concept they meant (brand or ingredient)
    related          -> ingredient (IN), brand (BN) and product (SCD/SBD) concepts
    ndcs             -> NDCs for each product concept, joined to NADAC by NDC
Path 2 (always, and the only path if RxNorm is down): fuzzy-match the names
    (what they typed plus the RxNorm ingredient/brand names) against NADAC
    descriptions with rapidfuzz.

Products are NADAC rows grouped by description, because CMS sets one rate for a
group of equivalent NDCs.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd
import requests
from rapidfuzz import fuzz

RXNAV = "https://rxnav.nlm.nih.gov/REST"
TIMEOUT = 10
MAX_PRODUCT_CONCEPTS = 40   # caps NDC lookups per search (RxNav allows ~20 req/s)

JsonGetter = Callable[[str], "dict | None"]


# --- HTTP ----------------------------------------------------------------

def http_get_json(url: str) -> dict | None:
    """GET JSON with a 10 s timeout and one retry. Returns None on failure, never raises."""
    for _ in range(2):
        try:
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "RxReceipt"})
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            continue
    return None


class RxNorm:
    """Thin RxNav client. `get_json` is injectable so tests never touch the network."""

    def __init__(self, get_json: JsonGetter = http_get_json):
        self.get_json = get_json
        self.ok = True  # flips to False if any call failed, so the UI can say so

    def _get(self, path: str) -> dict | None:
        data = self.get_json(f"{RXNAV}{path}")
        if data is None:
            self.ok = False
        return data

    def approximate(self, term: str, max_entries: int = 8) -> list[dict]:
        q = requests.utils.quote(term)
        data = self._get(f"/approximateTerm.json?term={q}&maxEntries={max_entries}&option=1") or {}
        cands = (data.get("approximateGroup") or {}).get("candidate") or []
        seen, out = set(), []
        for c in cands:
            if c.get("rxcui") and c["rxcui"] not in seen:
                seen.add(c["rxcui"])
                out.append(c)
        return out

    def properties(self, rxcui: str) -> dict:
        return ((self._get(f"/rxcui/{rxcui}/properties.json") or {}).get("properties")) or {}

    def related(self, rxcui: str, ttys: str = "IN+BN+SCD+SBD") -> dict[str, list[dict]]:
        data = self._get(f"/rxcui/{rxcui}/related.json?tty={ttys}") or {}
        out: dict[str, list[dict]] = {}
        for g in (data.get("relatedGroup") or {}).get("conceptGroup") or []:
            if g.get("conceptProperties"):
                out.setdefault(g["tty"], []).extend(g["conceptProperties"])
        return out

    def ndcs(self, rxcui: str) -> list[str]:
        data = self._get(f"/rxcui/{rxcui}/ndcs.json") or {}
        lst = ((data.get("ndcGroup") or {}).get("ndcList") or {}).get("ndc") or []
        return [re.sub(r"\D", "", n).zfill(11) for n in lst]


# --- products ------------------------------------------------------------

FORM_WORDS = {
    "TAB": "tablet", "TABS": "tablets", "CAP": "capsule", "SUSP": "suspension", "SOLN": "solution",
    "OINT": "ointment", "CRM": "cream", "INH": "inhaler", "SYR": "syrup", "ER": "ER", "DR": "DR",
    "HCL": "HCl", "MG": "mg", "MCG": "mcg", "ML": "mL", "GM": "g", "G": "g", "MEQ": "mEq",
}


def split_name(description: str) -> tuple[str, str]:
    """'ATORVASTATIN 20 MG TABLET' -> ('ATORVASTATIN', '20 MG TABLET')."""
    m = re.search(r"\s(?=\d|\.\d)", description)
    if not m:
        return description.strip(), ""
    return description[: m.start()].strip(), description[m.end():].strip()


def pretty(description: str) -> str:
    """'AMOXICILLIN 400 MG/5 ML SUSP' -> 'Amoxicillin 400 mg/5 mL suspension'."""
    name, rest = split_name(description)

    def word(w: str) -> str:
        return FORM_WORDS.get(w.upper(), w.lower())

    def name_word(w: str) -> str:
        return FORM_WORDS.get(w.upper(), w.capitalize() if len(w) > 2 else w)

    name_p = re.sub(r"[A-Za-z]+", lambda m: name_word(m.group()), name)
    rest_p = re.sub(r"[A-Za-z]+", lambda m: word(m.group()), rest)
    return f"{name_p} {rest_p}".strip()


def build_products(nadac: pd.DataFrame) -> pd.DataFrame:
    """Group NADAC NDC rows into products (one CMS rate group per description).

    Prefers NDCs that are in the latest weekly report; an NDC that dropped out of
    the report keeps its last rate but is marked not current.
    """
    df = nadac.copy()
    latest = df["as_of_date"].max() if "as_of_date" in df else None
    df["current"] = (df["as_of_date"] == latest) if latest is not None else True
    keys = ["description", "pricing_unit", "classification"]
    for k in keys:
        df[k] = df[k].astype(str)
    # If any NDC in a group is current, price the group from its current NDCs only.
    any_current = df.groupby(keys, observed=True)["current"].transform("any")
    df = df[df["current"] | ~any_current]
    g = df.groupby(keys, observed=True, sort=False)
    out = g.agg(
        nadac_per_unit=("nadac_per_unit", "median"),
        ndc=("ndc", "first"),
        n_ndcs=("ndc", "size"),
        effective_date=("effective_date", "max"),
        as_of_date=("as_of_date", "max") if "as_of_date" in df else ("effective_date", "max"),
        current=("current", "any"),
        otc=("otc", "first") if "otc" in df else ("ndc", "size"),
        generic_nadac_per_unit=("generic_nadac_per_unit", "median")
        if "generic_nadac_per_unit" in df else ("nadac_per_unit", lambda s: float("nan")),
    ).reset_index()
    out["ndcs"] = g["ndc"].agg(list).values
    out["otc"] = out["otc"].astype(str)
    parts = out["description"].map(split_name)
    out["name"] = parts.str[0]
    out["strength_form"] = parts.str[1]
    out["label"] = out["description"].map(pretty)
    out["is_brand"] = out["classification"].str.startswith("B")
    out["key"] = out["description"] + "|" + out["pricing_unit"] + "|" + out["classification"]
    return out.sort_values("description").reset_index(drop=True)


def generic_equivalent(products: pd.DataFrame, product: pd.Series) -> pd.Series | None:
    """For a brand product, find the generic product NADAC points at.

    NADAC gives brand rows a 'corresponding generic NADAC per unit'. We look for
    the generic product with that exact rate and the same strength and unit.
    Returns None if there's no generic rate or no unambiguous match.
    """
    gp = product.get("generic_nadac_per_unit")
    if not product.get("is_brand") or gp is None or pd.isna(gp):
        return None
    cand = products[(~products["is_brand"]) & (products["pricing_unit"] == product["pricing_unit"])
                    & ((products["nadac_per_unit"] - gp).abs() < 1e-6)]
    strength = _strength_tokens(product["strength_form"])
    cand = cand[cand["strength_form"].map(_strength_tokens) == strength]
    if cand.empty:
        return None
    return cand.sort_values("n_ndcs", ascending=False).iloc[0]


def _strength_tokens(s: str) -> tuple:
    """Numbers and units only, so 'TABLET' vs 'TAB' doesn't matter: '20 MG TABLET' -> ('20','MG')."""
    return tuple(re.findall(r"\d[\d.,/]*|MG|MCG|ML|GM|%|UNIT|MEQ", str(s).upper()))


# --- search --------------------------------------------------------------

@dataclass
class SearchResult:
    query: str
    products: pd.DataFrame                       # matching NADAC products, best first
    ingredients: list[str] = field(default_factory=list)  # RxNorm IN names (e.g. atorvastatin)
    brands: list[str] = field(default_factory=list)       # RxNorm BN names (e.g. Lipitor)
    unpriced: list[str] = field(default_factory=list)     # RxNorm products with no NADAC rate
    rxnorm_ok: bool = True
    used_rxnorm: bool = False

    @property
    def found(self) -> bool:
        return not self.products.empty


# Words people type -> how NADAC abbreviates them.
FORM_ALIASES = {
    "TABLET": ("TAB",), "TABLETS": ("TAB",), "CAPSULE": ("CAP",), "CAPSULES": ("CAP",),
    "SUSPENSION": ("SUSP",), "SOLUTION": ("SOLN", "SOL"), "OINTMENT": ("OINT",), "CREAM": ("CREAM", "CRM"),
    "LIQUID": ("SOLN", "SUSP", "LIQ", "SYRUP", "ELIX"), "INHALER": ("INH", "HFA", "AER"),
}


def _first_number(s: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else float("inf")


def _query_numbers(q: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", q)


def _name_score(term: str, name: str) -> float:
    t, n = term.upper().strip(), name.upper().strip()
    if not t:
        return 0.0
    if n == t:
        return 100.0
    if n.startswith(t + " ") or n.startswith(t + "-") or n.startswith(t + "("):
        return 95.0
    return 0.6 * fuzz.token_set_ratio(t, n) + 0.4 * fuzz.ratio(t, n)


def fuzzy_products(products: pd.DataFrame, terms: list[str], threshold: float = 82) -> pd.DataFrame:
    """Products whose drug name matches any term. Adds a 'score' column."""
    terms = [t for t in dict.fromkeys(t.strip() for t in terms) if t]
    if not terms or products.empty:
        return products.iloc[0:0].assign(score=[])
    names = products["name"].unique()
    best = {n: max(_name_score(t, n) for t in terms) for n in names}
    scores = products["name"].map(best)
    return products.assign(score=scores)[scores >= threshold]


def _clean_query(q: str) -> str:
    q = re.sub(r"\s+", " ", q).strip()
    return q[:100]


def search(query: str, products: pd.DataFrame, rx: RxNorm | None = None) -> SearchResult:
    query = _clean_query(query)
    empty = products.iloc[0:0].assign(score=[])
    if len(query) < 2:
        return SearchResult(query, empty)

    ingredients: list[str] = []
    brands: list[str] = []
    ndc_hits: set[str] = set()
    product_names: dict[str, str] = {}  # rxcui -> name for SCD/SBD
    rxnorm_ok, used = True, False

    if rx is not None:
        cands = rx.approximate(query)
        if cands:
            used = True
            top = cands[0]["rxcui"]
            rel = rx.related(top)
            props = rx.properties(top)
            tty = props.get("tty", "")
            if tty in ("SCD", "SBD"):
                product_names[top] = props.get("name", "")
            if tty == "IN":
                ingredients.append(props.get("name", ""))
            if tty == "BN":
                brands.append(props.get("name", ""))
            ingredients += [c["name"] for c in rel.get("IN", [])]
            brands += [c["name"] for c in rel.get("BN", [])]
            for t in ("SCD", "SBD"):
                for c in rel.get(t, []):
                    product_names[c["rxcui"]] = c["name"]
            # Brand -> generic: also pull the ingredient's generic products.
            if tty in ("BN", "SBD") and rel.get("IN"):
                for c in rx.related(rel["IN"][0]["rxcui"], "SCD").get("SCD", []):
                    product_names[c["rxcui"]] = c["name"]
            concepts = list(product_names)[:MAX_PRODUCT_CONCEPTS]
            with ThreadPoolExecutor(max_workers=8) as pool:
                ndc_lists = list(pool.map(rx.ndcs, concepts))
            for rxcui, ndcs in zip(concepts, ndc_lists):
                ndc_hits.update(ndcs)
        rxnorm_ok = rx.ok

    ingredients = list(dict.fromkeys(i for i in ingredients if i))
    brands = list(dict.fromkeys(b for b in brands if b))

    # Name terms: what they typed (minus strength numbers) + RxNorm names.
    typed_name = re.sub(r"\d.*$", "", query).strip() or query
    terms = [typed_name] + ingredients + brands
    by_name = fuzzy_products(products, terms)
    by_ndc = products[products["ndcs"].map(lambda lst: any(n in ndc_hits for n in lst))] if ndc_hits else empty
    if not by_ndc.empty:
        by_ndc = by_ndc.assign(score=100.0)
    hits = pd.concat([by_ndc, by_name]).drop_duplicates("key", keep="first")

    # Rank: products matching the strength they typed, then name score, then
    # what they typed (brand vs generic), then by description.
    nums = _query_numbers(query)
    if not hits.empty:
        typed_upper = typed_name.split()[0].upper() if typed_name.split() else ""
        # Extra words like "cream" or "suspension" rank matching forms first.
        form_words = [FORM_ALIASES.get(w, (w,)) for w in re.findall(r"[A-Z]{3,}", typed_name.upper())[1:]]
        hits = hits.assign(
            _strength=hits["strength_form"].map(lambda s: all(n in _strength_tokens(s) for n in nums) if nums else True),
            _form=hits["description"].map(lambda d: sum(any(a in d for a in w) for w in form_words)),
            _typed=hits["name"].str.upper().str.startswith(typed_upper),
            _num=hits["strength_form"].map(_first_number),
        ).sort_values(["_strength", "_form", "_typed", "score", "current", "is_brand", "name", "_num", "description"],
                      ascending=[False, False, False, False, False, True, True, True, True])
        hits = hits.drop(columns=["_strength", "_form", "_typed", "_num"]).reset_index(drop=True)

    # RxNorm products that have NDCs but no NADAC rate (common for specialty drugs).
    unpriced: list[str] = []
    if used and hits.empty and product_names:
        unpriced = sorted(set(product_names.values()))[:12]

    return SearchResult(query, hits, ingredients, brands, unpriced, rxnorm_ok, used)
