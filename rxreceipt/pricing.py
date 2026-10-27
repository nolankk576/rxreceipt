"""Receipt math. Pure functions, no Streamlit, so it is easy to test.

Every money line is rounded to cents (half up) *before* it is summed, so the
receipt the user sees always adds up exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# Defaults the user can change in the app.
DEFAULT_DISPENSE_FEE = 10.00   # bottle, label, pharmacist time (a round, editable guess)
DEFAULT_MARKUP_PCT = 15.0      # cost-plus formula as Cost Plus Drugs publicizes it
DEFAULT_PHARMACY_FEE = 5.00
DEFAULT_SHIPPING = 5.25

DAYS_SUPPLY_OPTIONS = (30, 60, 90)
PAY_METHODS = ("cash", "insurance copay", "not sure")


def cents(x: float | int | Decimal) -> float:
    """Round money to cents, half up (0.125 -> 0.13), as people expect on a receipt."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fmt_money(x: float, signed: bool = False) -> str:
    """$1,234.50 ; with signed=True: +$1.00 / −$1.00 (true minus sign)."""
    s = f"${abs(cents(x)):,.2f}"
    if signed:
        return ("+" if x > 0 else "−" if x < 0 else "") + s
    return ("−" if x < 0 else "") + s


def fills_per_year(days_supply: int) -> float:
    if days_supply <= 0:
        raise ValueError("days supply must be positive")
    return 365 / days_supply


# --- units ---------------------------------------------------------------

UNIT_SHORT = {"EA": "each", "ML": "mL", "GM": "g"}


def unit_short(pricing_unit: str) -> str:
    return UNIT_SHORT.get(str(pricing_unit).upper(), str(pricing_unit).lower())


def unit_noun(pricing_unit: str, description: str = "", plural: bool = True) -> str:
    """What one NADAC pricing unit is, in words: 'tablets', 'capsules', 'mL', 'g'."""
    u = str(pricing_unit).upper()
    if u == "ML":
        return "mL"
    if u == "GM":
        return "g"
    d = f" {description.upper()} "
    for keys, one, many in (((" TAB", "TABLET", " CHEW"), "tablet", "tablets"),
                            ((" CAP", "CAPSULE"), "capsule", "capsules"),
                            ((" PATCH",), "patch", "patches"),
                            ((" SUPP",), "suppository", "suppositories"),
                            ((" PACKET", " PKT"), "packet", "packets")):
        if any(k in d for k in keys):
            return many if plural else one
    return "units" if plural else "unit"


def per_unit_label(pricing_unit: str, description: str = "") -> str:
    """'per tablet', 'per mL', 'per g'."""
    return "per " + unit_noun(pricing_unit, description, plural=False)


# --- the receipt ---------------------------------------------------------

@dataclass(frozen=True)
class ReceiptInputs:
    nadac_per_unit: float | None   # None when NADAC has no rate for the product
    quantity: float                # in the NADAC pricing unit
    pricing_unit: str              # EA / ML / GM
    days_supply: int
    paid: float
    pay_method: str = "cash"
    dispense_fee: float = DEFAULT_DISPENSE_FEE
    markup_pct: float = DEFAULT_MARKUP_PCT
    pharmacy_fee: float = DEFAULT_PHARMACY_FEE
    shipping: float = DEFAULT_SHIPPING
    generic_nadac_per_unit: float | None = None  # for brand products with a generic


@dataclass(frozen=True)
class ReceiptMath:
    has_rate: bool
    drug_cost: float | None          # NADAC x qty
    dispense_fee: float
    fair_price: float | None         # drug cost + cost to dispense
    costplus_drug: float | None
    costplus_markup: float | None
    costplus_fee: float
    costplus_shipping: float
    costplus_total: float | None
    paid: float
    markup_dollars: float | None     # paid - pharmacy drug cost
    markup_pct: float | None         # vs pharmacy drug cost, percent
    fills_per_year: float
    yearly_paid: float
    yearly_vs_costplus: float | None  # (paid - cost-plus) per fill x fills; + means you could save
    yearly_vs_fair: float | None
    generic_drug_cost: float | None
    generic_costplus_total: float | None


def compute(inp: ReceiptInputs) -> ReceiptMath:
    if inp.quantity <= 0:
        raise ValueError("quantity must be positive")
    if inp.paid < 0:
        raise ValueError("amount paid can't be negative")
    fpy = fills_per_year(inp.days_supply)
    paid = cents(inp.paid)
    fee = cents(inp.dispense_fee)
    cp_fee = cents(inp.pharmacy_fee)
    ship = cents(inp.shipping)

    def costplus(per_unit: float) -> tuple[float, float, float]:
        drug = cents(per_unit * inp.quantity)
        markup = cents(drug * inp.markup_pct / 100)
        return drug, markup, cents(drug + markup + cp_fee + ship)

    generic_drug = generic_cp = None
    if inp.generic_nadac_per_unit is not None and inp.generic_nadac_per_unit > 0:
        generic_drug, _, generic_cp = costplus(inp.generic_nadac_per_unit)

    if inp.nadac_per_unit is None:
        return ReceiptMath(False, None, fee, None, None, None, cp_fee, ship, None, paid,
                           None, None, fpy, cents(paid * fpy), None, None, generic_drug, generic_cp)

    drug, markup, cp_total = costplus(inp.nadac_per_unit)
    fair = cents(drug + fee)
    markup_dollars = cents(paid - drug)
    markup_pct = (paid - drug) / drug * 100 if drug > 0 else None
    return ReceiptMath(
        has_rate=True,
        drug_cost=drug,
        dispense_fee=fee,
        fair_price=fair,
        costplus_drug=drug,
        costplus_markup=markup,
        costplus_fee=cp_fee,
        costplus_shipping=ship,
        costplus_total=cp_total,
        paid=paid,
        markup_dollars=markup_dollars,
        markup_pct=markup_pct,
        fills_per_year=fpy,
        yearly_paid=cents(paid * fpy),
        yearly_vs_costplus=cents((paid - cp_total) * fpy),
        yearly_vs_fair=cents((paid - fair) * fpy),
        generic_drug_cost=generic_drug,
        generic_costplus_total=generic_cp,
    )


def compound(yearly: float, rate_pct: float, years: int) -> list[float]:
    """Value at the end of each year if `yearly` is set aside every year and grows at rate_pct.

    Contributions are made at the end of each year (ordinary annuity). Illustration only.
    """
    out, total = [], 0.0
    r = rate_pct / 100
    for _ in range(years):
        total = total * (1 + r) + yearly
        out.append(cents(total))
    return out
