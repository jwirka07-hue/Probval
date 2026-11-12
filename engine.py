"""
CRE Valuation Engine — v1, Step 1: direct capitalization.

Design rule from the spec: the AI reads and writes; this module does the math.
Every number in the memo must trace back to a function in this file.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass
class OperatingInputs:
    units: int
    avg_rent: float                 # $/unit/month, in-place
    vacancy: float                  # % of GPR
    concessions_bad_debt: float     # % of GPR
    other_income: float             # $/unit/month
    opex_per_unit: float            # $/unit/year, EXCLUDING taxes, mgmt, reserves
    mgmt_fee: float                 # % of EGI
    reserves_per_unit: float        # $/unit/year


@dataclass
class TaxInputs:
    current_tax_bill: float         # seller's in-place bill (broker case)
    assessment_ratio: float = 0.40  # Georgia assesses at 40% of FMV
    millage: float = 0.030          # 30 mills = $30 per $1,000 of assessed value

    @property
    def effective_rate(self) -> float:
        """Tax as a % of market value."""
        return self.assessment_ratio * self.millage


def operating_statement(op: OperatingInputs) -> dict:
    """Revenue and expenses down to NOI before property taxes."""
    gpr = op.units * op.avg_rent * 12
    vacancy = gpr * op.vacancy
    concessions = gpr * op.concessions_bad_debt
    other = op.units * op.other_income * 12
    egi = gpr - vacancy - concessions + other

    opex = op.units * op.opex_per_unit
    mgmt = egi * op.mgmt_fee
    reserves = op.units * op.reserves_per_unit
    total_exp = opex + mgmt + reserves

    return {
        "gpr": gpr,
        "vacancy": -vacancy,
        "concessions_bad_debt": -concessions,
        "other_income": other,
        "egi": egi,
        "opex": opex,
        "management": mgmt,
        "reserves": reserves,
        "expenses_before_tax": total_exp,
        "noi_before_tax": egi - total_exp,
    }


def direct_cap(op: OperatingInputs, tax: TaxInputs, cap_rate: float,
               reassess: bool = True) -> dict:
    """
    Direct cap value.

    reassess=False -> broker case: uses the seller's current tax bill.
    reassess=True  -> adjusted case: taxes reset to the purchase price.
        Taxes depend on value and value depends on taxes, so solve:
            V = (NOI_pre - t*V) / c   ->   V = NOI_pre / (c + t)
        Because taxes are linear in value this closed form is exact;
        no iteration is needed.
    """
    stmt = operating_statement(op)
    noi_pre = stmt["noi_before_tax"]

    if reassess:
        value = noi_pre / (cap_rate + tax.effective_rate)
        taxes = tax.effective_rate * value
    else:
        taxes = tax.current_tax_bill
        value = (noi_pre - taxes) / cap_rate

    noi = noi_pre - taxes
    return {
        **stmt,
        "taxes": taxes,
        "noi": noi,
        "cap_rate": cap_rate,
        "value": value,
        "value_per_unit": value / op.units,
        "case": "adjusted (taxes reassessed)" if reassess else "broker (in-place taxes)",
    }


def cap_rate_sensitivity(op: OperatingInputs, tax: TaxInputs,
                         cap_rates: list[float], reassess: bool = True) -> list[dict]:
    rows = []
    for c in cap_rates:
        r = direct_cap(op, tax, c, reassess)
        rows.append({"cap_rate": c, "value": r["value"], "per_unit": r["value_per_unit"]})
    return rows
