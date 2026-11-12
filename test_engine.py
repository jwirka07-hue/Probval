"""
Benchmark test: the spec's 120-unit Athens worked example.
If this fails, the engine is wrong. Run with: python -m pytest -q
"""
import pytest
from engine import OperatingInputs, TaxInputs, direct_cap, cap_rate_sensitivity

OP = OperatingInputs(
    units=120, avg_rent=1450, vacancy=0.06, concessions_bad_debt=0.02,
    other_income=75, opex_per_unit=5200, mgmt_fee=0.03, reserves_per_unit=300,
)
TAX = TaxInputs(current_tax_bill=180_000, assessment_ratio=0.40, millage=0.030)


def test_operating_statement():
    r = direct_cap(OP, TAX, 0.055)
    assert r["gpr"] == 2_088_000
    assert r["egi"] == pytest.approx(2_028_960)
    assert r["expenses_before_tax"] == pytest.approx(720_868.8)
    assert r["noi_before_tax"] == pytest.approx(1_308_091.2)


def test_broker_case():
    r = direct_cap(OP, TAX, 0.055, reassess=False)
    assert r["noi"] == pytest.approx(1_128_091, abs=1)
    assert r["value"] == pytest.approx(20_510_745, abs=5)  # spec rounds mgmt to $60,869 mid-calc; engine is unrounded


def test_adjusted_case():
    r = direct_cap(OP, TAX, 0.055, reassess=True)
    assert r["value"] == pytest.approx(19_523_746, abs=5)  # spec rounds mgmt to $60,869 mid-calc; engine is unrounded
    assert r["taxes"] == pytest.approx(234_285, abs=1)
    assert r["value_per_unit"] == pytest.approx(162_698, abs=1)
    # Internal consistency: NOI / cap must equal value
    assert r["noi"] / 0.055 == pytest.approx(r["value"])


def test_tax_flag_impact():
    broker = direct_cap(OP, TAX, 0.055, reassess=False)["value"]
    adjusted = direct_cap(OP, TAX, 0.055, reassess=True)["value"]
    assert broker - adjusted == pytest.approx(987_000, abs=1_000)
    assert (broker - adjusted) / broker == pytest.approx(0.048, abs=0.001)


def test_sensitivity_table():
    rows = cap_rate_sensitivity(OP, TAX, [0.0525, 0.055, 0.0575])
    for r, expected in zip(rows, [20_280_481, 19_523_746, 18_821_453]):
        assert r["value"] == pytest.approx(expected, abs=5)




# ======================================================================
# Underwriting engine
# ======================================================================
import datetime as dt
import io
from dataclasses import replace

import pandas as pd

import export
import market_data as md
import quality
import rentroll
from underwriting import RANGE_LABEL, Inputs, ValuationError, underwrite

TODAY = dt.date(2026, 11, 11)
MF = Inputs(sector="multifamily", market="Atlanta, GA", size=120, gpr=120 * 1450 * 12, physical_vacancy=0.05,
            opex=624_000, other_income=108_000, pclass="B")


def suites(rows, building_sf=None, default="nnn", mkt=9.0):
    t = pd.DataFrame(rows, columns=["Suite", "Tenant", "SF", "Annual Rent", "Lease Type", "Lease End",
                                    "Market Rent $/SF", "Vacant"])
    return rentroll.review_commercial(t, building_sf, default, mkt, today=TODAY)


def commercial(review, sector="industrial", market="Atlanta, GA", **kw):
    base = dict(sector=sector, market=market, size=review["total_sf"], gpr=review["gpr_annual"],
                physical_vacancy=review["physical_vacancy"], opex=150_000, suites=review["suites"], pclass="B")
    base.update(kw)
    return Inputs(**base)


LONG = [["100", "A Co", 60000, 540000, "NNN", "2034-12-31", None, False],
        ["200", "B Co", 40000, 360000, "NNN", "2033-12-31", None, False]]


# ---------------- Rent roll review ----------------
def test_duplicate_suites_are_critical():
    rv = suites([["100", "A", 10000, 90000, "NNN", "2030-01-01", None, False],
                 ["100", "B", 10000, 90000, "NNN", "2030-01-01", None, False]])
    assert rv["critical"] and "more than once" in rv["critical"][0]


def test_missing_area_is_added_as_vacant():
    rv = suites(LONG, building_sf=120_000)
    assert any(s["suite"] == "Unlisted area" and s["vacant"] and s["sf"] == 20_000 for s in rv["suites"])
    assert rv["critical"]                               # 17% missing > 10%
    assert rv["physical_vacancy"] == pytest.approx(20_000 / 120_000)


def test_roll_larger_than_building_is_critical():
    rv = suites(LONG, building_sf=80_000)
    assert any("more than the building" in c for c in rv["critical"])


def test_unknown_lease_type_uses_default_with_warning():
    rv = suites([["100", "A", 10000, 90000, None, "2030-01-01", None, False]], default="base_year")
    assert rv["suites"][0]["lease_type"] == "base_year"
    assert any("no recognized lease type" in m for _, m in rv["flags"])


def test_expired_and_missing_dates():
    rv = suites([["100", "A", 10000, 90000, "NNN", "2025-01-01", None, False],
                 ["200", "B", 10000, 90000, "NNN", None, None, False]])
    assert rv["suites"][0]["months_left"] == 1 and rv["suites"][1]["months_left"] == 36


def test_per_suite_market_rent_override():
    rv = suites([["100", "A", 10000, 90000, "NNN", "2030-01-01", 12.0, False],
                 ["200", "", 10000, 0, None, None, None, True]], mkt=9.0)
    assert rv["suites"][0]["market_psf"] == 12.0 and rv["suites"][1]["market_psf"] == 9.0
    assert rv["gpr_annual"] == 90000 + 90000


def test_mf_vacant_units_priced_by_floorplan():
    plans = pd.DataFrame({"Unit type": ["1x1", "2x2"], "Units": [10, 10], "Occupied": [10, 8],
                          "Avg in-place rent": [1000, 1500], "Market rent": [None, 1600]})
    t = rentroll.plans_to_totals(plans)
    assert t["gpr_annual"] == pytest.approx((10 * 1000 + 8 * 1500 + 2 * 1600) * 12)
    assert t["loss_to_lease_annual"] == pytest.approx(100 * 8 * 12)


def test_mf_duplicate_units_flagged():
    df = pd.DataFrame({"Unit": ["101", "101", "102"], "Rent": [1000, 1000, 1100]})
    assert any(s == "critical" for s, _ in rentroll.summarize(df)["flags"])


# ---------------- Validation and quality ----------------
@pytest.mark.parametrize("bad", [dict(size=0), dict(gpr=0), dict(physical_vacancy=1.0), dict(opex=-1),
                                 dict(collected_rent=0), dict(discount_override=0.5)])
def test_invalid_inputs_raise_clear_errors(bad):
    with pytest.raises(ValuationError):
        underwrite(replace(MF, **bad))


def test_negative_noi_is_refused():
    with pytest.raises(ValuationError, match="expenses exceed"):
        underwrite(replace(MF, opex=3_000_000))


def test_quality_flags_monthly_vs_annual_rent():
    q = quality.check("industrial", "Atlanta, GA", 100_000, 85_000, 0.05, 150_000)   # $0.85/SF = monthly entered
    assert q["grade"] in ("B", "C") and any("outside the usual" in m for m in q["warnings"])


def test_quality_high_vacancy_is_critical():
    assert quality.check("office", "Atlanta, GA", 50_000, 1_400_000, 0.6, 350_000)["critical"]


# ---------------- Lease-level DCF ----------------
def test_near_term_expiration_lowers_value_vs_long_leases():
    long_ = underwrite(commercial(suites(LONG)))
    short = [[*r[:5], "2027-06-30", *r[6:]] for r in LONG]
    s = underwrite(commercial(suites(short)))
    assert s["value"] < long_["value"]
    assert s["discount"] > long_["discount"]                      # rollover risk adjustment
    assert s["weights"]["dcf"] > long_["weights"]["dcf"]          # complexity shifts weight to DCF
    assert s["flows"][0]["leasing_costs"] < 0                     # TI/LC at rollover year 1


def test_lower_renewal_probability_lowers_value():
    rv = suites([[*r[:5], "2028-06-30", *r[6:]] for r in LONG])
    hi = underwrite(commercial(rv, leasing={"renewal_prob": 0.9}))
    lo = underwrite(commercial(rv, leasing={"renewal_prob": 0.3}))
    assert lo["dcf_value"] < hi["dcf_value"]


def test_market_rent_reset_moves_value():
    rows = [[*r[:5], "2027-12-31", *r[6:]] for r in LONG]
    below = underwrite(commercial(suites(rows, mkt=12.0)))       # in-place $9 is below market → upside at reset
    above = underwrite(commercial(suites(rows, mkt=7.0)))
    assert below["dcf_value"] > above["dcf_value"]


def test_nnn_recovers_more_than_gross():
    nnn = underwrite(commercial(suites(LONG)))
    gross = underwrite(commercial(suites([[*r[:4], "Gross", *r[5:]] for r in LONG])))
    assert nnn["flows"][0]["recoveries"] > 0 and gross["flows"][0]["recoveries"] == 0
    assert nnn["value"] > gross["value"]


def test_vacant_suite_lease_up_costs_reduce_value():
    full = underwrite(commercial(suites(LONG)))
    vac = underwrite(commercial(suites(LONG + [["300", "", 50000, 0, None, None, None, True]])))
    assert vac["leaseup_cost"] > 0 and vac["leaseup_months"] > 0
    assert vac["value"] / vac["size"] < full["value"] / full["size"]


# ---------------- Taxes, expenses ----------------
def test_sale_state_taxes_follow_value_cycle_state_keeps_bill():
    ga = underwrite(replace(MF, current_tax=100_000))
    assert ga["flows"][0]["taxes"] == pytest.approx(-md.MARKETS["Atlanta, GA"]["tax_apartment"] * ga["value"], rel=0.02)
    nc = underwrite(replace(MF, market="Charlotte, NC", current_tax=100_000))
    assert nc["flows"][0]["taxes"] == pytest.approx(-100_000)


def test_abatement_raises_value():
    assert underwrite(replace(MF, abatement=50_000, abatement_years=5))["value"] > underwrite(MF)["value"]


def test_insurance_heavy_expenses_grow_faster():
    base = underwrite(MF)
    ins = underwrite(replace(MF, opex_breakdown={"insurance": 400_000}))
    assert ins["flows"][9]["opex"] < base["flows"][9]["opex"]      # more negative = larger expense
    assert ins["value"] < base["value"]


# ---------------- Cap rate, discount, reconciliation ----------------
def test_cap_confidence_labeled():
    r = underwrite(MF)
    assert r["cap_confidence"] in ("High", "Medium", "Low")
    assert md.cap_benchmark("multifamily", "Athens, GA")["confidence"] == "Low"


def test_comps_blend_cap_and_add_sales_weight():
    comps = [{"price": 24e6, "size": 120, "months_ago": 4, "cap": 0.055, "pclass": "B"},
             {"price": 23e6, "size": 118, "months_ago": 8, "cap": 0.056},
             {"price": 25e6, "size": 125, "months_ago": 2}]
    r = underwrite(replace(MF, comps=comps))
    assert r["weights"]["sales"] > 0 and r["sales_value"] > 0
    assert sum(r["weights"].values()) == pytest.approx(100)


def test_discount_rate_has_documented_buildup():
    r = underwrite(MF)
    assert sum(v for _, v, _ in r["discount_rows"]) == pytest.approx(r["discount"])
    assert r["discount"] > r["cap_rate"]


def test_mf_stabilized_favors_direct_cap_with_reasons():
    r = underwrite(MF)
    assert r["weights"]["dc"] > r["weights"]["dcf"] and r["weight_reasons"]


def test_range_is_scenario_labeled_and_brackets():
    r = underwrite(MF)
    assert r["range_label"] == RANGE_LABEL and "not a statistical" in RANGE_LABEL
    assert r["low"] < r["value"] < r["high"]


def test_not_sure_class_widens_range():
    a, b = underwrite(MF), underwrite(replace(MF, pclass=None))
    assert (b["high"] - b["low"]) > (a["high"] - a["low"])


def test_sensitivity_centers_match():
    r = underwrite(MF)
    assert r["sensitivity"]["rows"][2]["values"][1] == pytest.approx(r["value"], rel=1e-6)
    assert r["sens_disc_exit"]["rows"][2]["values"][2] == pytest.approx(r["dcf_value"], rel=1e-6)


def test_excel_export_builds():
    r = underwrite(commercial(suites(LONG)))
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(export.build(r, "Test", [("Market", "Atlanta")])))
    assert {"Summary", "Cash Flow", "Rates", "Sensitivity", "Lease Schedule", "Sources"} <= set(wb.sheetnames)


def test_quick_mode_skips_lease_risk_adjustments():
    rows = [[*r[:5], "2027-06-30", *r[6:]] for r in LONG]
    rv = suites(rows)
    full = underwrite(commercial(rv))
    quick = underwrite(commercial(rv, quick=True))
    assert quick["discount"] < full["discount"]
    assert not any("expire" in x for x in quick["weight_reasons"])


def test_quick_home_estimate():
    import home
    r = home.quick_estimate(2100, [{"price": 420000, "sf": 2000}, {"price": 455000, "sf": 2250}])
    assert r["low"] < r["value"] < r["high"] and 400000 < r["value"] < 470000


def _quick_suites(answer, sector="office", size=100000, occ=0.9, psf=28.0, lt="gross"):
    s = [{"suite": f"g{i}", "tenant": "x", "sf": size * occ * sh, "rent": size * occ * sh * psf, "lease_type": lt,
          "months_left": m, "vacant": False, "market_psf": psf} for i, (sh, m) in enumerate(md.lease_profile(answer, sector))]
    s.append({"suite": "v", "tenant": "", "sf": size * (1 - occ), "rent": 0, "lease_type": lt, "months_left": None,
              "vacant": True, "market_psf": psf})
    return Inputs(sector=sector, market="Atlanta, GA", size=size, gpr=size * psf, physical_vacancy=1 - occ,
                  opex=750_000, suites=s, quick=answer == "Not sure")


def test_quick_lease_expiration_answer_orders_value():
    v = {a: underwrite(_quick_suites(a), sensitivity=False)["value"]
         for a in ["Within 12 months", "1–3 years", "More than 3 years"]}
    assert v["Within 12 months"] < v["1–3 years"] < v["More than 3 years"]


def test_volatile_source_caps_confidence():
    assert md.cap_benchmark("industrial", "Atlanta, GA")["confidence"] != "High"
    assert "not a property-specific" in md.cap_benchmark("industrial", "Atlanta, GA")["label"]


def test_input_quality_note_disclaims_accuracy():
    assert "does not measure" in quality.check("industrial", "Atlanta, GA", 100000, 900000, 0.05, 125000)["scope"]


# ---------------- Subtype, reasonableness, rent basis, validation ----------------
import checks
import validation


def _ind(subtype, size=100000, occ=0.95, psf=9.0, **kw):
    s = [{"suite": "a", "tenant": "x", "sf": size * occ, "rent": size * occ * psf, "lease_type": "nnn",
          "months_left": 40, "vacant": False, "market_psf": psf},
         {"suite": "v", "tenant": "", "sf": size * (1 - occ), "rent": 0, "lease_type": "nnn", "months_left": None,
          "vacant": True, "market_psf": psf}]
    return Inputs(sector="industrial", market="Atlanta, GA", size=size, gpr=size * psf, physical_vacancy=1 - occ,
                  opex=125_000, suites=s, subtype=subtype, **kw)


def test_subtype_changes_cap_and_leasing():
    bulk = underwrite(_ind("Bulk distribution"), sensitivity=False)
    mfg = underwrite(_ind("Manufacturing"), sensitivity=False)
    small = underwrite(_ind("Small-bay / multi-tenant"), sensitivity=False)
    assert mfg["cap_rate"] > bulk["cap_rate"] > small["cap_rate"]
    assert mfg["value"] < bulk["value"]


def test_reasonableness_flags_but_never_changes_value():
    inp = _ind("Bulk distribution", psf=30.0)          # rent far above market -> value far above benchmark
    r = underwrite(inp, sensitivity=False)
    rc = checks.reasonableness(r, inp)
    assert rc["status"] == "above" and rc["reasons"]
    assert r["value"] == underwrite(inp, sensitivity=False)["value"]
    ok = checks.reasonableness(underwrite(_ind("Bulk distribution"), sensitivity=False), _ind("Bulk distribution"))
    assert ok["status"] in ("within", "below", "above")


def test_reasonableness_without_benchmark():
    inp = replace(_ind(None), market="Birmingham, AL")
    assert checks.reasonableness(underwrite(inp, sensitivity=False), inp)["status"] == "none"


def test_estimated_rent_is_flagged_and_less_reliable():
    r = underwrite(_ind("Bulk distribution", rent_basis="estimated"), sensitivity=False)
    assert any("estimate of market rent" in w for w in r["warnings"])
    inp = _ind("Bulk distribution")
    rc = checks.reasonableness(r, inp)
    hi = checks.reliability(inp, "High", rc, {"rent_actual": True, "opex_given": True, "tax_given": True,
                                               "leases_known": True})
    lo = checks.reliability(inp, "High", rc, {"rent_actual": False, "opex_given": False, "tax_given": False,
                                               "leases_known": False})
    assert ["Lower", "Moderate", "Higher"].index(lo["label"]) < ["Lower", "Moderate", "Higher"].index(hi["label"])


def test_cap_override_used_as_is():
    r = underwrite(_ind("Bulk distribution", cap_override=0.07), sensitivity=False)
    assert r["cap_rate"] == pytest.approx(0.07)


def test_validation_harness_runs_three_modes():
    res = validation.run(validation.template())
    row = res.iloc[0]
    for m in ("quick", "detailed", "detailed_cap"):
        assert row[f"{m}_value"] > 0
    assert "Median abs error" in validation.summarize(res)
