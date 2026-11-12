"""
Run a valuation from scratch.

    python run.py              -> prompts you for every input, blank start
    python run.py deal.json    -> re-runs a deal you saved earlier

Every run saves its inputs and outputs to deals/<name>.json (the audit trail).
"""
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from engine import OperatingInputs, TaxInputs, direct_cap, cap_rate_sensitivity

# (field, prompt, kind)  kind: "int" | "money" | "pct"
OP_FIELDS = [
    ("units", "Number of units", "int"),
    ("avg_rent", "Average in-place rent ($/unit/month)", "money"),
    ("vacancy", "Vacancy (% of GPR, e.g. 6)", "pct"),
    ("concessions_bad_debt", "Concessions + bad debt (% of GPR)", "pct"),
    ("other_income", "Other income ($/unit/month)", "money"),
    ("opex_per_unit", "Operating expenses ($/unit/year, excl. taxes, mgmt, reserves)", "money"),
    ("mgmt_fee", "Management fee (% of EGI)", "pct"),
    ("reserves_per_unit", "Replacement reserves ($/unit/year)", "money"),
]
TAX_FIELDS = [
    ("current_tax_bill", "Seller's current property tax bill ($/year)", "money"),
    ("assessment_ratio", "Assessment ratio (% of market value; Georgia = 40)", "pct"),
    ("millage", "Millage rate (mills, e.g. 30)", "mills"),
]


def ask(prompt: str, kind: str) -> float:
    while True:
        raw = input(f"  {prompt}: ").strip().replace(",", "").replace("$", "").replace("%", "")
        try:
            val = float(raw)
        except ValueError:
            print("    Enter a number.")
            continue
        if val < 0:
            print("    Must be zero or positive.")
            continue
        if kind == "int":
            return int(val)
        if kind == "pct":
            return val / 100
        if kind == "mills":
            return val / 1000
        return val


def collect_inputs() -> dict:
    print("\n=== New deal ===")
    name = input("  Deal name: ").strip() or "untitled"
    print("\n-- Operations --")
    op = {f: ask(p, k) for f, p, k in OP_FIELDS}
    print("\n-- Property taxes --")
    tax = {f: ask(p, k) for f, p, k in TAX_FIELDS}
    print("\n-- Valuation --")
    cap = ask("Cap rate (%, e.g. 5.5)", "pct")
    return {"name": name, "operating": op, "taxes": tax, "cap_rate": cap}


def money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def report(deal: dict) -> dict:
    op = OperatingInputs(**deal["operating"])
    tax = TaxInputs(**deal["taxes"])
    cap = deal["cap_rate"]
    t = tax.effective_rate

    broker = direct_cap(op, tax, cap, reassess=False)
    adj = direct_cap(op, tax, cap, reassess=True)
    b = adj  # operating lines are identical in both cases

    print(f"\n=== {deal['name']} — valuation ===\n")
    print("Revenue")
    print(f"  GPR             = {op.units} x ${op.avg_rent:,.0f} x 12             = {money(b['gpr'])}")
    print(f"  Vacancy         = {money(b['gpr'])} x {op.vacancy:.2%}           = {money(b['vacancy'])}")
    print(f"  Concessions/BD  = {money(b['gpr'])} x {op.concessions_bad_debt:.2%}           = {money(b['concessions_bad_debt'])}")
    print(f"  Other income    = {op.units} x ${op.other_income:,.0f} x 12               = {money(b['other_income'])}")
    print(f"  EGI                                                = {money(b['egi'])}")
    print("\nExpenses before taxes")
    print(f"  Operating       = {op.units} x ${op.opex_per_unit:,.0f}                  = {money(b['opex'])}")
    print(f"  Management      = {money(b['egi'])} x {op.mgmt_fee:.2%}           = {money(b['management'])}")
    print(f"  Reserves        = {op.units} x ${op.reserves_per_unit:,.0f}                    = {money(b['reserves'])}")
    print(f"  Total                                              = {money(b['expenses_before_tax'])}")
    print(f"\nNOI before taxes  = {money(b['egi'])} - {money(b['expenses_before_tax'])} = {money(b['noi_before_tax'])}")

    print("\nBroker case (seller's current tax bill)")
    print(f"  NOI   = {money(b['noi_before_tax'])} - {money(broker['taxes'])} = {money(broker['noi'])}")
    print(f"  Value = {money(broker['noi'])} / {cap:.2%} = {money(broker['value'])}  ({money(broker['value_per_unit'])}/unit)")

    print("\nAdjusted case (taxes reset to purchase price)")
    print(f"  Effective tax rate = {tax.assessment_ratio:.0%} x {tax.millage*1000:g} mills = {t:.3%} of value")
    print(f"  V = {money(b['noi_before_tax'])} / ({cap:.2%} + {t:.3%}) = {money(adj['value'])}")
    print(f"  Taxes = {t:.3%} x {money(adj['value'])} = {money(adj['taxes'])}")
    print(f"  NOI   = {money(adj['noi'])}   check: {money(adj['noi'])} / {cap:.2%} = {money(adj['noi']/cap)}")
    print(f"  Value per unit = {money(adj['value_per_unit'])}")

    gap = broker["value"] - adj["value"]
    print(f"\nTax reassessment impact: {money(gap)} ({gap/broker['value']:.1%} of broker value)")

    caps = [cap - 0.0025, cap, cap + 0.0025]
    rows = cap_rate_sensitivity(op, tax, caps)
    print("\nSensitivity (adjusted case)")
    print(f"  {'Cap rate':>9} {'Value':>15} {'Per unit':>11}")
    for r in rows:
        print(f"  {r['cap_rate']:>9.2%} {money(r['value']):>15} {money(r['per_unit']):>11}")

    return {"broker": broker, "adjusted": adj, "tax_impact": gap, "sensitivity": rows}


def save(deal: dict, outputs: dict) -> Path:
    Path("deals").mkdir(exist_ok=True)
    slug = "".join(c if c.isalnum() else "_" for c in deal["name"].lower()).strip("_") or "deal"
    path = Path("deals") / f"{slug}.json"
    path.write_text(json.dumps(
        {**deal, "run_at": datetime.now().isoformat(timespec="seconds"), "outputs": outputs},
        indent=2, default=str))
    return path


if __name__ == "__main__":
    if len(sys.argv) > 1:
        saved = json.loads(Path(sys.argv[1]).read_text())
        deal = {k: saved[k] for k in ("name", "operating", "taxes", "cap_rate")}
    else:
        deal = collect_inputs()
    outputs = report(deal)
    print(f"\nSaved to {save(deal, outputs)}")
