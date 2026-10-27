"""The Receipt page: search a drug, enter what you paid, get the receipt."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from rxreceipt import charts, data, pricing, receipt, ui
from rxreceipt.search import generic_equivalent

EXAMPLE = dict(q="atorvastatin 20 mg", product_key="ATORVASTATIN 20 MG TABLET|EA|G",
               qty=90.0, days=90, paid=45.0, method="cash")
DEFAULT_QTY = {"EA": 30.0, "ML": 100.0, "GM": 30.0}
MAX_OPTIONS = 40


def load_example() -> None:
    for k, v in EXAMPLE.items():
        st.session_state[k] = v
    st.session_state["show_receipt"] = True


def reset_assumptions() -> None:
    st.session_state.update(fee=pricing.DEFAULT_DISPENSE_FEE, markup=pricing.DEFAULT_MARKUP_PCT,
                            cp_fee=pricing.DEFAULT_PHARMACY_FEE, ship=pricing.DEFAULT_SHIPPING)


def bignums(items: list[tuple[str, str, str, str]]) -> None:
    """Row of big-number tiles: (label, value, sub, css class)."""
    cells = "".join(
        f'<div class="rx-bignum"><div class="k">{html.escape(k)}</div>'
        f'<div class="v {c}">{html.escape(v)}</div><div class="s">{html.escape(s)}</div></div>'
        for k, v, s, c in items)
    st.html(f'<div class="rx-bignums">{cells}</div>')


def option_label(p: pd.Series) -> str:
    kind = "brand" if p["is_brand"] else "generic"
    rate = receipt.fmt_rate(p["nadac_per_unit"])
    stale = "" if p["current"] else " · not in latest report"
    return f"{p['label']} · {kind} · {rate} {pricing.per_unit_label(p['pricing_unit'], p['description'])}{stale}"


def checklist(items: list[tuple[str, str]]) -> None:
    rows = "".join(f'<div class="rx-check"><div class="box" aria-hidden="true">✓</div>'
                   f'<div class="t"><b>{html.escape(t)}</b><span>{body}</span></div></div>' for t, body in items)
    st.html(f'<div class="rx-card">{rows}</div>')


DEFAULTS = dict(days=30, method="cash", paid=None, fee=pricing.DEFAULT_DISPENSE_FEE,
                markup=pricing.DEFAULT_MARKUP_PCT, cp_fee=pricing.DEFAULT_PHARMACY_FEE, ship=pricing.DEFAULT_SHIPPING)


def render() -> None:
    for k, v in DEFAULTS.items():  # seed once; widgets then read only from session state
        st.session_state.setdefault(k, v)
    products = data.load_products()
    meta = data.load_meta()
    as_of = meta.get("as_of_date", "unknown")

    st.html("""<div class="rx-hero"><div class="rx-kicker">Prescription price check</div>
      <h1>RxReceipt — see what your prescription really costs.</h1>
      <p>What pharmacies pay for it, what a transparent cost-plus price would be, what you paid,
      and how much you could save in a year.</p></div>""")
    st.button("Try an example", on_click=load_example, type="primary", icon=":material/receipt_long:",
              help="Atorvastatin 20 mg, 90 tablets, paid $45 cash")

    if products is None:
        ui.data_missing()
        ui.footer(meta)
        return

    st.subheader("1 · Your prescription")
    query = st.text_input("Drug name", key="q", placeholder="e.g. Lipitor, metformin 500 mg, amoxicillin suspension",
                          help="Brand or generic name. Add the strength to narrow it down.")
    if not query or len(query.strip()) < 2:
        ui.empty_state("💊", "Start with the drug name",
                       "Type a brand or generic name above, or press 'Try an example'.")
        ui.footer(meta)
        return

    with st.spinner("Looking up matching products…"):
        result = data.search(query, products, as_of)

    if result.ingredients or result.brands:
        bits = []
        if result.ingredients:
            bits.append("generic name: **" + ", ".join(i.lower() for i in result.ingredients[:3]) + "**")
        if result.brands:
            bits.append("brand: **" + ", ".join(result.brands[:4]) + "**")
        st.caption("RxNorm match · " + " · ".join(bits))
    if not result.rxnorm_ok:
        st.caption("The RxNorm lookup service didn't answer, so we matched names directly. Results may be less complete.")

    if not result.found:
        if result.unpriced:
            st.warning("**NADAC has no rate for this drug.** RxNorm knows it, but CMS publishes no acquisition "
                       "cost for it. That's common for specialty drugs and some brand drugs, so we can't show "
                       "what pharmacies pay.", icon=":material/info:")
            st.markdown("What we do know, from RxNorm, are the products sold under this name:\n\n"
                        + "\n".join(f"- {html.escape(n)}" for n in result.unpriced))
            no_rate_receipt(meta)
        else:
            ui.empty_state("🔎", f"No match for “{query.strip()}”",
                           "Check the spelling, try the generic name, or drop the strength.")
        ui.footer(meta)
        return

    opts = result.products.head(MAX_OPTIONS)
    keys = list(opts["key"])
    by_key = {k: opts.iloc[i] for i, k in enumerate(keys)}
    current = st.session_state.get("product_key")
    index = keys.index(current) if current in keys else 0
    choice = st.selectbox(f"Pick your exact product ({len(result.products)} found)", keys, index=index,
                          format_func=lambda k: option_label(by_key[k]))
    st.session_state["product_key"] = choice
    p = by_key[choice]
    unit = p["pricing_unit"]
    noun = pricing.unit_noun(unit, p["description"])

    c1, c2 = st.columns(2)
    if "qty" not in st.session_state:
        st.session_state["qty"] = DEFAULT_QTY.get(unit, 30.0)
    qty = c1.number_input(f"Quantity ({noun})", key="qty", min_value=0.01, max_value=100000.0, step=1.0,
                          help=f"NADAC prices this product {pricing.per_unit_label(unit, p['description'])} "
                               f"(pricing unit: {unit}). Enter how many {noun} were in your fill.")
    days = c2.radio("Days supply", pricing.DAYS_SUPPLY_OPTIONS, key="days", horizontal=True,
                    format_func=lambda d: f"{d} days")
    c3, c4 = st.columns(2)
    paid = c3.number_input("What you paid ($)", key="paid", min_value=0.0, max_value=100000.0, step=1.0,
                           placeholder="e.g. 45.00", format="%.2f")
    method = c4.radio("How you paid", pricing.PAY_METHODS, key="method", horizontal=False)

    with st.expander("Adjust the assumptions"):
        fee = st.number_input("Typical cost to dispense ($)", key="fee", min_value=0.0, max_value=100.0, step=0.5,
                              help="A pharmacy's cost per fill: bottle, label, pharmacist and staff time.")
        markup = st.slider("Cost-plus markup (%)", 0.0, 50.0, key="markup", step=1.0)
        cp_fee = st.slider("Cost-plus pharmacy fee ($)", 0.0, 20.0, key="cp_fee", step=0.25)
        ship = st.slider("Shipping ($)", 0.0, 15.0, key="ship", step=0.25)
        st.button("Reset to defaults", on_click=reset_assumptions)
        st.caption("Cost-plus estimate: an estimate using a cost-plus formula like the one Cost Plus Drugs "
                   "publicizes; their real price uses their own costs and may differ.")

    if paid is None:
        ui.empty_state("🧾", "Add what you paid", "Enter the amount from your pharmacy receipt to see the comparison.")
        ui.footer(meta)
        return

    generic = generic_equivalent(products, p)
    inp = pricing.ReceiptInputs(
        nadac_per_unit=float(p["nadac_per_unit"]), quantity=float(qty), pricing_unit=unit,
        days_supply=int(days), paid=float(paid), pay_method=method, dispense_fee=float(fee),
        markup_pct=float(markup), pharmacy_fee=float(cp_fee), shipping=float(ship),
        generic_nadac_per_unit=None if pd.isna(p["generic_nadac_per_unit"]) else float(p["generic_nadac_per_unit"]),
    )
    m = pricing.compute(inp)

    st.subheader("2 · Your receipt")
    if method == "insurance copay":
        st.info("**You paid a copay.** Insurance is often the cheapest way to fill a prescription, so this "
                "compares your copay with cash options. Cash isn't always cheaper, and cash purchases may "
                "not count toward your deductible.", icon=":material/health_and_safety:")
    if not p["current"]:
        st.caption(f"Heads-up: this product's NDCs weren't in the latest weekly NADAC report; "
                   f"the rate shown is the last one CMS published ({p['effective_date']}).")

    y = m.yearly_vs_costplus
    bignums([
        ("You paid", pricing.fmt_money(m.paid), f"for {receipt.fmt_qty(qty)} {noun}", ""),
        ("Pharmacies pay about", pricing.fmt_money(m.drug_cost), "NADAC × quantity", ""),
        ("Yearly difference",
         f"save {pricing.fmt_money(y)}" if y > 0 else f"{pricing.fmt_money(y, signed=True)}" if y < 0 else "$0.00",
         ("a year you could save vs the cost-plus estimate" if y > 0
          else "a year: you already pay less than the cost-plus estimate" if y < 0
          else "same as the cost-plus estimate"),
         "rx-good" if y > 0 else ""),
    ])

    lines = receipt.build_lines(inp, m, p["label"], p["description"])
    st.html(receipt.render_html(lines, p["ndc"], as_of))

    d1, d2 = st.columns(2)
    fname = f"rxreceipt-{p['ndc']}"
    d1.download_button("Download PNG", receipt.render_png(lines, p["ndc"], as_of), f"{fname}.png", "image/png",
                       icon=":material/image:", width="stretch")
    d2.download_button("Download PDF", receipt.render_pdf(lines, p["ndc"], as_of), f"{fname}.pdf",
                       "application/pdf", icon=":material/picture_as_pdf:", width="stretch")

    with st.expander("How we calculated this"):
        how_we_calculated(inp, m, p)

    st.subheader("3 · The price ladder")
    st.caption("Gray bars are reference prices. The last bar is what you paid, labeled with how far it is above (+) "
               "or below (−) the cost-plus estimate.")
    fig = charts.price_ladder(m)
    st.plotly_chart(fig, config=charts.CONFIG, width="stretch")

    st.subheader("4 · How to pay less")
    checklist(pay_less_items(inp, m, p, generic, noun))
    ui.footer(meta)


def pay_less_items(inp, m, p, generic, noun) -> list[tuple[str, str]]:
    e = html.escape
    items = []
    if inp.pay_method == "insurance copay":
        items.append(("Ask for the cash price and compare it with your copay",
                      "Sometimes cash is lower than a copay, sometimes not. Note: cash purchases may not count "
                      "toward your insurance deductible or out-of-pocket maximum."))
    else:
        items.append(("Ask for the cash price, and compare it with your insurance copay if you have coverage",
                      "Pharmacies can quote both. Cash purchases may not count toward a deductible."))
    if inp.days_supply < 90:
        items.append(("Ask about a 90-day supply",
                      f"You're filling every {inp.days_supply} days ({m.fills_per_year:.1f} fills a year). "
                      "Fewer fills can mean fewer dispensing fees and copays. Ask whether 90 days is right for you."))
    else:
        items.append(("You're already on a 90-day supply", "That usually means the fewest fees and copays per year."))
    if p["is_brand"]:
        if m.generic_drug_cost is not None:
            gname = generic["label"] if generic is not None else "the generic version"
            items.append((f"A generic exists: {gname}",
                          f"Pharmacies pay about <b>{pricing.fmt_money(m.generic_drug_cost)}</b> for "
                          f"{receipt.fmt_qty(inp.quantity)} {e(noun)} of the generic, vs "
                          f"<b>{pricing.fmt_money(m.drug_cost)}</b> for {e(p['label'])} (NADAC). "
                          "Ask your pharmacist or prescriber whether the generic is right for you."))
        else:
            items.append(("No generic rate in NADAC",
                          "NADAC lists no generic equivalent rate for this brand product, so there may not be "
                          "a generic yet. Your pharmacist can confirm."))
    items.append(("Compare a few pharmacies",
                  "Prices for the same drug vary a lot between pharmacies. Check a couple of local ones and a "
                  "mail-order cost-plus pharmacy, which publishes its markup."))
    items.append(("Keep taking your medication as prescribed",
                  "Don't stop or change a medication to save money without talking to your prescriber or pharmacist. "
                  "They can often help find a lower-cost option."))
    return items


def how_we_calculated(inp, m, p) -> None:
    per = pricing.per_unit_label(inp.pricing_unit, p["description"])
    noun = pricing.unit_noun(inp.pricing_unit, p["description"])
    fm = pricing.fmt_money
    st.markdown(f"""
All money is rounded to the cent at each line, so the receipt adds up.

| Line | Formula | Amount |
|---|---|---|
| Pharmacy's drug cost | NADAC {receipt.fmt_rate(inp.nadac_per_unit)} {per} × {receipt.fmt_qty(inp.quantity)} {noun} | {fm(m.drug_cost)} |
| Typical cost to dispense | your setting | {fm(m.dispense_fee)} |
| Fair-ish price | drug cost + cost to dispense | {fm(m.fair_price)} |
| Cost-plus markup | {inp.markup_pct:g}% × {fm(m.drug_cost)} | {fm(m.costplus_markup)} |
| Cost-plus estimate | {fm(m.drug_cost)} + {fm(m.costplus_markup)} + {fm(m.costplus_fee)} fee + {fm(m.costplus_shipping)} shipping | {fm(m.costplus_total)} |
| Markup over pharmacy cost | {fm(m.paid)} − {fm(m.drug_cost)} | {fm(m.markup_dollars, signed=True)} |
| Fills per year | 365 ÷ {inp.days_supply} days | {m.fills_per_year:.2f} |
| Yearly difference | ({fm(m.paid)} − {fm(m.costplus_total)}) × {m.fills_per_year:.2f} | {fm(m.yearly_vs_costplus, signed=True)} |

- **NADAC** for *{html.escape(p['description'])}*: median of {p['n_ndcs']} NDC(s) in this CMS rate group,
  effective {p['effective_date']}. Pricing unit: **{inp.pricing_unit}** ({noun}).
- A positive yearly difference means you pay more than the cost-plus estimate; negative means you pay less.
""")


def no_rate_receipt(meta: dict) -> None:
    """When NADAC has no rate: still show what they pay per year."""
    c1, c2 = st.columns(2)
    paid = c1.number_input("What you paid ($)", key="paid_norate", min_value=0.0, value=None, format="%.2f")
    days = c2.radio("Days supply", pricing.DAYS_SUPPLY_OPTIONS, key="days_norate", horizontal=True,
                    format_func=lambda d: f"{d} days")
    if paid is not None:
        per_year = pricing.cents(paid * pricing.fills_per_year(days))
        st.markdown(f"At {pricing.fills_per_year(days):.1f} fills a year, that's **{pricing.fmt_money(per_year)} a year**. "
                    "Ask your pharmacist about the cash price, your plan's preferred pharmacy, and any "
                    "manufacturer assistance program.")


with ui.friendly_errors("the receipt"):
    render()
