"""Download the current NADAC file from data.medicaid.gov and write a slim parquet.

NADAC (National Average Drug Acquisition Cost) is published by CMS weekly, as one
dataset per calendar year. Each yearly CSV holds every weekly report, so an NDC
appears many times; we keep only its most recent row.

Usage:
    python scripts/refresh_nadac.py                 # current year (falls back to newest found)
    python scripts/refresh_nadac.py --dataset-id ID  # a specific dataset
    python scripts/refresh_nadac.py --csv local.csv  # skip the download

Writes data/nadac_latest.parquet and data/nadac_meta.json. The app reads only these.

Why the CSV and not the DKAN query API: the API pages at 500 rows and compares
dates and numbers as strings when sorting or filtering, which silently gives
wrong "latest" rows. The CSV is the whole file, as CMS publishes it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_PARQUET = DATA_DIR / "nadac_latest.parquet"
OUT_META = DATA_DIR / "nadac_meta.json"

API = "https://data.medicaid.gov/api/1"
# Known yearly dataset identifiers. Newer years are discovered from the catalog.
KNOWN_DATASETS = {2026: "fbb83258-11c7-47f5-8b18-5f8e79f7e704"}
TIMEOUT = 60
USER_AGENT = "RxReceipt data refresh (+https://github.com/nolankk576/rxreceipt)"

# Our column name -> normalised CMS header names we accept for it.
COLUMNS = {
    "description": ["ndc_description"],
    "ndc": ["ndc"],
    "nadac_per_unit": ["nadac_per_unit"],
    "effective_date": ["effective_date"],
    "pricing_unit": ["pricing_unit"],
    "pharmacy_type": ["pharmacy_type_indicator"],
    "otc": ["otc"],
    "explanation_code": ["explanation_code"],
    "classification": ["classification_for_rate_setting"],
    "generic_nadac_per_unit": ["corresponding_generic_drug_nadac_per_unit"],
    "generic_effective_date": ["corresponding_generic_drug_effective_date"],
    "as_of_date": ["as_of_date"],
}
REQUIRED = ["description", "ndc", "nadac_per_unit", "effective_date", "pricing_unit"]


def log(msg: str) -> None:
    print(msg, flush=True)


def get(url: str, **kw) -> requests.Response:
    """GET with a timeout and a few retries (CMS is occasionally slow)."""
    last = None
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:  # noqa: PERF203
            last = e
            log(f"  attempt {attempt + 1} failed for {url}: {e}")
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"giving up on {url}: {last}")


def norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h).strip().lower()).strip("_")


def discover_datasets() -> dict[int, dict]:
    """Return {year: {"id", "title"}} for the yearly NADAC datasets in the catalog."""
    found: dict[int, dict] = {}
    try:
        items = get(f"{API}/metastore/schemas/dataset/items").json()
    except Exception as e:  # catalog is a nice-to-have; known IDs still work
        log(f"catalog lookup failed ({e}); using known dataset IDs only")
        items = []
    for it in items if isinstance(items, list) else []:
        title = str(it.get("title", ""))
        m = re.search(r"\b(20\d\d)\b", title)
        # The weekly NADAC sets are titled like "NADAC (National Average Drug
        # Acquisition Cost) 2026". Skip the "comparison" and "first time" sets.
        if (m and "nadac" in title.lower() and "national average drug acquisition cost" in title.lower()
                and "comparison" not in title.lower() and "first time" not in title.lower()):
            found[int(m.group(1))] = {"id": it.get("identifier"), "title": title}
    for year, ident in KNOWN_DATASETS.items():
        found.setdefault(year, {"id": ident, "title": f"NADAC {year}"})
    return found


def find_csv_urls(obj) -> list[str]:
    """Walk dataset metadata and return every downloadURL that looks like a CSV."""
    urls = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "downloadURL" and isinstance(v, str) and ".csv" in v.lower():
                urls.append(v)
            else:
                urls.extend(find_csv_urls(v))
    elif isinstance(obj, list):
        for v in obj:
            urls.extend(find_csv_urls(v))
    return urls


def dataset_metadata(dataset_id: str) -> dict:
    return get(f"{API}/metastore/schemas/dataset/items/{dataset_id}").json()


def download(url: str, dest: Path) -> None:
    log(f"downloading {url}")
    with requests.get(url, timeout=TIMEOUT, stream=True, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    log(f"  {dest.stat().st_size / 1e6:.1f} MB")


def parse_dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", format="mixed").dt.date


def slim(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename CMS headers to ours, keep the latest row per NDC, set compact dtypes."""
    headers = {norm_header(c): c for c in raw.columns}
    log(f"CSV headers: {list(raw.columns)}")
    rename = {}
    for ours, options in COLUMNS.items():
        for opt in options:
            if opt in headers:
                rename[headers[opt]] = ours
                break
    missing = [c for c in REQUIRED if c not in rename.values()]
    if missing:
        raise SystemExit(f"NADAC CSV is missing required columns {missing}; headers were {list(raw.columns)}")
    df = raw[list(rename)].rename(columns=rename)

    df["ndc"] = df["ndc"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(11)
    df["description"] = df["description"].astype(str).str.strip()
    df["nadac_per_unit"] = pd.to_numeric(df["nadac_per_unit"], errors="coerce")
    df["pricing_unit"] = df["pricing_unit"].astype(str).str.strip().str.upper()
    for c in ("effective_date", "as_of_date", "generic_effective_date"):
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce", format="mixed")
    if "generic_nadac_per_unit" in df:
        df["generic_nadac_per_unit"] = pd.to_numeric(df["generic_nadac_per_unit"], errors="coerce")
    for c in ("otc", "classification", "pharmacy_type", "explanation_code"):
        if c in df:
            df[c] = df[c].astype("string").str.strip().str.upper()

    df = df.dropna(subset=["nadac_per_unit", "effective_date"])
    order = [c for c in ("as_of_date", "effective_date") if c in df]
    df = df.sort_values(order).drop_duplicates("ndc", keep="last")

    for c in ("effective_date", "as_of_date", "generic_effective_date"):
        if c in df:
            df[c] = df[c].dt.date
    for c in ("pricing_unit", "otc", "classification", "pharmacy_type"):
        if c in df:
            df[c] = df[c].astype("category")
    df["nadac_per_unit"] = df["nadac_per_unit"].astype("float64")
    return df.sort_values(["description", "ndc"]).reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset-id")
    ap.add_argument("--year", type=int, default=dt.date.today().year)
    ap.add_argument("--csv", type=Path, help="use a local CSV instead of downloading")
    args = ap.parse_args(argv)

    meta: dict = {"source": "CMS NADAC (National Average Drug Acquisition Cost), data.medicaid.gov"}
    with tempfile.TemporaryDirectory() as tmp:
        if args.csv:
            csv_path = args.csv
            meta.update(dataset_id=args.dataset_id, csv_url=str(args.csv.name))
        else:
            if args.dataset_id:
                dataset_id, title = args.dataset_id, None
            else:
                sets = discover_datasets()
                log(f"NADAC datasets found: { {y: s['id'] for y, s in sorted(sets.items())} }")
                year = args.year if args.year in sets else max(y for y in sets if y <= args.year)
                dataset_id, title = sets[year]["id"], sets[year]["title"]
            md = dataset_metadata(dataset_id)
            urls = find_csv_urls(md)
            log(f"dataset {dataset_id} ({md.get('title', title)}), modified {md.get('modified')}; CSV URLs: {urls}")
            if urls:
                url = urls[0]
            else:  # DKAN can also export the datastore as CSV
                url = f"{API}/datastore/query/{dataset_id}/0/download?format=csv"
            csv_path = Path(tmp) / "nadac.csv"
            download(url, csv_path)
            meta.update(dataset_id=dataset_id, title=md.get("title", title),
                        dataset_modified=md.get("modified"), csv_url=url)

        raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""])
        log(f"raw rows: {len(raw):,}")
        df = slim(raw)

    DATA_DIR.mkdir(exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False, compression="zstd")
    as_of = df["as_of_date"].max() if "as_of_date" in df else df["effective_date"].max()
    meta.update(
        as_of_date=str(as_of),
        latest_effective_date=str(df["effective_date"].max()),
        rows=int(len(df)),
        columns=list(df.columns),
    )
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n")
    log(f"wrote {OUT_PARQUET.relative_to(ROOT)}: {len(df):,} NDCs, "
        f"{OUT_PARQUET.stat().st_size / 1e6:.2f} MB, as of {as_of}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
