"""About the data: sources, dates, what each number means, limitations."""
import streamlit as st

from rxreceipt import data, ui


def render() -> None:
    meta = data.load_meta()
    products = data.load_products()
    st.title("About the data")
    st.markdown("RxReceipt uses free U.S. government data. No accounts, no API keys, no paid data.")

    st.subheader("NADAC: what pharmacies pay")
    if meta:
        n_products = f"{len(products):,}" if products is not None else "—"
        st.markdown(f"""
- **Dataset:** {meta.get('title', 'NADAC')} (CMS, [data.medicaid.gov](https://data.medicaid.gov/))
- **Prices as of:** {meta.get('as_of_date', '—')} · newest effective date {meta.get('latest_effective_date', '—')}
- **Size:** {meta.get('rows', 0):,} NDCs (package codes), grouped into {n_products} products
- **File:** [{meta.get('csv_url', '').rsplit('/', 1)[-1]}]({meta.get('csv_url', '')})
""")
    else:
        ui.data_missing()
    st.markdown("""
**NADAC** (National Average Drug Acquisition Cost) is CMS's estimate of the average price retail
pharmacies pay to buy a drug from wholesalers and manufacturers. It comes from a monthly survey of
pharmacy invoices and is published weekly.

- It's per **pricing unit**: **EA** (each: a tablet, capsule, patch…), **ML** (milliliter) or **GM** (gram).
  RxReceipt always shows which, and never mixes them.
- It is **not net of rebates** or other after-the-sale discounts, and it is **not** what a patient pays.
- Some drugs have **no NADAC rate**, often specialty drugs, many brand drugs sold mainly through specialty
  or mail channels, and new products. RxReceipt says so instead of guessing.
- For brand drugs, NADAC lists the **corresponding generic NADAC**. That's where the "a generic
  exists" tip comes from.
- Products are NADAC descriptions; RxReceipt takes the median rate of the NDCs in each one. NDCs that dropped
  out of the latest weekly report are flagged.
""")

    st.subheader("RxNorm: matching what you type")
    st.markdown("""
The U.S. National Library of Medicine's [RxNav API](https://lhncbc.nlm.nih.gov/RxNav/APIs/) turns a name like
"Lipitor" into its generic name (atorvastatin), its products, and their NDCs, which RxReceipt joins to NADAC.
If RxNav is unreachable, RxReceipt matches names directly against NADAC descriptions. Lookups are cached for 7 days.
""")

    st.subheader("The receipt's other numbers")
    st.markdown("""
- **Typical cost to dispense** defaults to $10.00. It's an editable, round number for a pharmacy's per-fill
  cost (bottle, label, pharmacist and staff time), not a measured figure. Change it to see how it moves the "fair-ish" price.
- **Cost-plus estimate** = drug cost × (1 + markup) + pharmacy fee + shipping, with defaults of 15%, $5.00 and $5.25.
  It is an estimate using a cost-plus formula like the one Cost Plus Drugs publicizes; their real price uses
  their own costs and may differ. RxReceipt isn't affiliated with them or any pharmacy.
- **Yearly difference** = (what you paid − cost-plus estimate) × fills per year, where fills per year = 365 ÷ days supply.
""")

    st.subheader("Limitations")
    st.markdown("""
- NADAC is a national average for retail community pharmacies. Your pharmacy's real cost may be higher or lower.
- Insurance prices, copays, coupons and manufacturer programs aren't in any public dataset.
- Cash isn't always cheaper. With insurance, a copay is often the best price, and cash purchases may not count
  toward a deductible.
- This is education, not medical, financial or legal advice. Never stop or change a medication without
  talking to your prescriber.
""")

    st.subheader("Refreshing the data")
    st.markdown("""
A GitHub Action (`.github/workflows/refresh_nadac.yml`) runs every Thursday: it downloads the current NADAC CSV,
keeps the latest row per NDC, writes `data/nadac_latest.parquet`, and commits it if anything changed. Streamlit
Community Cloud then redeploys the app. To run it by hand: `python scripts/refresh_nadac.py`.
""")
    ui.footer(meta)


with ui.friendly_errors("the About page"):
    render()
