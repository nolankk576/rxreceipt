# RxReceipt — see what your prescription really costs

A receipt that tells the truth: what pharmacies pay for your prescription (CMS NADAC), what a transparent
cost-plus price would be, what you actually paid, and how much you could save in a year.

> _GIF: add a screen recording of "Try an example" here (docs/demo.gif)._

## The problem
Drug prices at the counter are opaque. The same generic can cost a few dollars or fifty, and most people
never see what the pharmacy paid for it. CMS publishes that number every week; RxReceipt puts it on a receipt.

## How it works
1. You type a drug name. **RxNorm** (NLM) normalizes it (Lipitor → atorvastatin) and finds its NDCs.
2. NDCs are joined to **NADAC**, which is pre-downloaded to `data/nadac_latest.parquet`. If RxNorm is down, names are fuzzy-matched with rapidfuzz.
3. The receipt shows pharmacy drug cost (NADAC × quantity), a "fair-ish" price (+ cost to dispense), a
   cost-plus estimate (× (1 + markup) + fee + shipping), what you paid, the markup, and the yearly difference.
4. A price ladder chart, a personalized "how to pay less" checklist, and PNG/PDF download.

## Data sources
| Source | What | As of |
|---|---|---|
| CMS NADAC via data.medicaid.gov | per-unit pharmacy acquisition cost | see `data/nadac_meta.json` (refreshed weekly by GitHub Actions) |
| NLM RxNorm (RxNav API) | name → product → NDC | live, cached 7 days |

## Limitations
NADAC is a national average for retail pharmacies, not net of rebates, and not a patient price. Many specialty
and some brand drugs have no NADAC rate (the app says so). Insurance prices and coupons aren't public. Cash isn't
always cheaper than a copay. The cost-plus estimate uses a formula like the one Cost Plus Drugs publicizes; their
real prices may differ. RxReceipt is not affiliated with any pharmacy.

## Disclaimer
Educational only, not medical, financial or legal advice. Don't stop or change a medication without talking to
your prescriber. Nothing you type is stored.

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q
streamlit run app.py
python scripts/refresh_nadac.py   # refresh the data (needs internet)
```

## Deploy (Streamlit Community Cloud)
1. Go to https://share.streamlit.io and sign in with GitHub.
2. **Create app → Deploy a public app from GitHub**.
3. Repository `nolankk576/rxreceipt`, branch `main`, main file path `app.py`.
4. Advanced settings → Python 3.12. Deploy.
The weekly `Refresh NADAC data` workflow commits new data, which redeploys the app automatically.

## License
MIT. IBM Plex Mono font: SIL Open Font License (`assets/fonts/OFL.txt`).
