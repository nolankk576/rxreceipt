import pytest
from rxreceipt.pricing import ReceiptInputs, compute, cents, fmt_money, fills_per_year, unit_noun, compound


def test_cents_rounds_half_up():
    assert cents(0.125) == 0.13 and cents(2.5722) == 2.57 and cents(-1.005) == -1.01


def test_example_receipt_math():
    m = compute(ReceiptInputs(0.02858, 90, "EA", 90, 45.0, "cash"))
    assert m.drug_cost == 2.57 and m.fair_price == 12.57
    assert m.costplus_markup == 0.39 and m.costplus_total == 13.21
    assert m.markup_dollars == 42.43
    assert m.yearly_vs_costplus == cents((45.0 - 13.21) * 365 / 90)


def test_lines_add_up():
    m = compute(ReceiptInputs(1.23456, 37, "EA", 30, 20.0))
    assert m.costplus_total == cents(m.costplus_drug + m.costplus_markup + m.costplus_fee + m.costplus_shipping)


def test_copay_lower_than_costplus_gives_negative_difference():
    m = compute(ReceiptInputs(0.5, 30, "EA", 30, 5.0, "insurance copay"))
    assert m.yearly_vs_costplus < 0


def test_no_rate():
    m = compute(ReceiptInputs(None, 30, "EA", 30, 100.0))
    assert not m.has_rate and m.drug_cost is None and m.yearly_paid == cents(100 * 365 / 30)


def test_units():
    assert unit_noun("ML", "AMOXICILLIN 400 MG/5 ML SUSP") == "mL"
    assert unit_noun("GM", "TRIAMCINOLONE 0.1% CREAM") == "g"
    assert unit_noun("EA", "ATORVASTATIN 20 MG TABLET") == "tablets"
    assert unit_noun("EA", "AMOXICILLIN 500 MG CAPSULE", plural=False) == "capsule"


def test_liquid_priced_per_ml():
    m = compute(ReceiptInputs(0.0213, 150, "ML", 30, 10.0))
    assert m.drug_cost == 3.20  # 0.0213 $/mL x 150 mL


def test_money_format_and_validation():
    assert fmt_money(1234.5) == "$1,234.50" and fmt_money(-2, signed=True) == "−$2.00"
    assert fills_per_year(30) == pytest.approx(12.1667, rel=1e-3)
    with pytest.raises(ValueError):
        compute(ReceiptInputs(1.0, 0, "EA", 30, 1.0))
    assert compound(100, 0, 3) == [100, 200, 300]
