"""Search tests. The NADAC rows here are a small hand-made fixture (prices are illustrative,
not real); RxNorm is mocked so tests never touch the network."""
import datetime as dt
import pandas as pd
from rxreceipt.search import RxNorm, build_products, generic_equivalent, search, pretty

D = dt.date(2026, 10, 21)
ROWS = [
    ("ATORVASTATIN 20 MG TABLET", "00093505910", 0.03, "EA", "G", None),
    ("LIPITOR 20 MG TABLET", "58151015677", 19.0, "EA", "B", 0.03),
    ("AMOXICILLIN 400 MG/5 ML SUSP", "00093416173", 0.04, "ML", "G", None),
    ("ELIQUIS 5 MG TABLET", "00003089421", 5.5, "EA", "B", None),
]
NADAC = pd.DataFrame([dict(description=d, ndc=n, nadac_per_unit=r, pricing_unit=u, classification=c,
                           generic_nadac_per_unit=g, effective_date=D, as_of_date=D, otc="N")
                      for d, n, r, u, c, g in ROWS])
P = build_products(NADAC)

RESP = {
    "approximateTerm.json?term=Lipitor": {"approximateGroup": {"candidate": [{"rxcui": "153165"}]}},
    "/rxcui/153165/properties": {"properties": {"rxcui": "153165", "name": "Lipitor", "tty": "BN"}},
    "/rxcui/153165/related.json?tty=IN+BN+SCD+SBD": {"relatedGroup": {"conceptGroup": [
        {"tty": "IN", "conceptProperties": [{"rxcui": "83367", "name": "atorvastatin"}]},
        {"tty": "SBD", "conceptProperties": [{"rxcui": "617314", "name": "atorvastatin 20 MG Oral Tablet [Lipitor]"}]}]}},
    "/rxcui/83367/related.json?tty=SCD": {"relatedGroup": {"conceptGroup": [
        {"tty": "SCD", "conceptProperties": [{"rxcui": "617312", "name": "atorvastatin 20 MG Oral Tablet"}]}]}},
    "/rxcui/617314/ndcs": {"ndcGroup": {"ndcList": {"ndc": ["58151015677"]}}},
    "/rxcui/617312/ndcs": {"ndcGroup": {"ndcList": {"ndc": ["00093505910"]}}},
    "approximateTerm.json?term=Humira": {"approximateGroup": {"candidate": [{"rxcui": "327361"}]}},
    "/rxcui/327361/properties": {"properties": {"name": "Humira", "tty": "BN"}},
    "/rxcui/327361/related.json?tty=IN+BN+SCD+SBD": {"relatedGroup": {"conceptGroup": [
        {"tty": "SBD", "conceptProperties": [{"rxcui": "1", "name": "adalimumab 40 MG/0.8ML Pen Injector [Humira]"}]}]}},
    "/rxcui/1/ndcs": {"ndcGroup": {"ndcList": {"ndc": ["00074433902"]}}},
}


def fake_get(url):
    for k, v in RESP.items():
        if k in url:
            return v
    return {}


def test_lipitor_maps_to_atorvastatin():
    r = search("Lipitor", P, RxNorm(fake_get))
    assert "atorvastatin" in r.ingredients
    assert {"LIPITOR 20 MG TABLET", "ATORVASTATIN 20 MG TABLET"} <= set(r.products["description"])
    assert r.products.iloc[0]["description"] == "LIPITOR 20 MG TABLET"  # what they typed comes first


def test_brand_with_generic():
    lip = P[P["description"] == "LIPITOR 20 MG TABLET"].iloc[0]
    g = generic_equivalent(P, lip)
    assert g is not None and g["description"] == "ATORVASTATIN 20 MG TABLET"


def test_liquid_priced_per_ml():
    r = search("amoxicillin suspension", P)
    top = r.products.iloc[0]
    assert top["pricing_unit"] == "ML" and pretty(top["description"]) == "Amoxicillin 400 mg/5 mL suspension"


def test_drug_with_no_nadac_rate():
    r = search("Humira", P, RxNorm(fake_get))
    assert not r.found and r.unpriced and "Humira" in r.unpriced[0]


def test_rxnorm_down_falls_back_to_fuzzy():
    r = search("lipitr", P, RxNorm(lambda url: None))
    assert not r.rxnorm_ok and r.found and r.products.iloc[0]["description"] == "LIPITOR 20 MG TABLET"
