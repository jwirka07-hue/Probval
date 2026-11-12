"""
Downloadable underwriting summary (.xlsx).

Sheets: Summary · Cash Flow · Rates · Sensitivity · Lease Schedule (commercial) · Sources
Cash-flow line items come from the engine (blue). NOI, present values, the year-10 sale, direct cap, the
weighted reconciliation, the discount-rate build-up and the discount × exit-cap grid are live formulas, so a
reviewer can change a rate or a weight and watch the value move.
"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import market_data as md

FONT = "Arial"
BLUE, BLACK, GREEN = "0000FF", "000000", "008000"
MONEY = '$#,##0;($#,##0);"-"'
PCT = '0.0%;(0.0%);"-"'
PCT2 = '0.00%'
KEY_FILL = "FFFF00"


def _f(bold=False, color=BLACK, size=10, italic=False):
    return Font(name=FONT, bold=bold, color=color, size=size, italic=italic)


def _put(ws, ref, value, fmt=None, bold=False, color=BLACK, comment=None, fill=None, wrap=False):
    c = ws[ref]
    c.value = value
    c.font = _f(bold=bold, color=color)
    if fmt:
        c.number_format = fmt
    if comment:
        c.comment = Comment(comment, "Estimator")
    if fill:
        c.fill = PatternFill("solid", fgColor=fill)
    if wrap:
        c.alignment = Alignment(wrap_text=True, vertical="top")
    return c


def _title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = _f(bold=True, size=12)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = _f(italic=True, color="666666", size=9)


CF_LINES = [
    ("Occupancy", "occupancy"), ("Potential rent", "potential_rent"), ("Vacancy", "vacancy"),
    ("Free rent", "free_rent"), ("Collection loss / concessions", "credit_loss"),
    ("Other income", "other_income"), ("Expense reimbursements", "recoveries"),
    ("Operating expenses", "opex"), ("Management", "management"), ("Reserves", "reserves"),
    ("Unreimbursed expenses", "nonrecoverable"), ("Property taxes", "taxes"),
    ("Tenant improvements, commissions, leasing", "leasing_costs"), ("One-time costs (repairs)", "one_time"),
]


def build(r: dict, title: str, inputs: list[tuple[str, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    cf = wb.create_sheet("Cash Flow")
    rates = wb.create_sheet("Rates")
    sens = wb.create_sheet("Sensitivity")
    leases = wb.create_sheet("Lease Schedule") if r["lease_events"] else None
    src = wb.create_sheet("Sources")
    years = len(r["flows"])
    last = get_column_letter(years + 1)

    # ------------------------------------------------------------------ Rates (discount build-up)
    _title(rates, "Discount rate build-up and cap rate evidence",
           "Blue = input; the discount rate is the live sum of its components and feeds the Summary.")
    _put(rates, "A4", "Component", bold=True)
    _put(rates, "B4", "Rate", bold=True)
    _put(rates, "C4", "Basis", bold=True)
    for i, (name, val, basis) in enumerate(r["discount_rows"]):
        _put(rates, f"A{5 + i}", name)
        _put(rates, f"B{5 + i}", val, PCT2, color=BLUE)
        _put(rates, f"C{5 + i}", basis)
    drow = 5 + len(r["discount_rows"])
    _put(rates, f"A{drow}", "Discount rate", bold=True)
    _put(rates, f"B{drow}", f"=SUM(B5:B{drow - 1})", PCT2, bold=True)
    ev = r["cap_evidence"]
    er = drow + 2
    _put(rates, f"A{er}", f"Cap rate benchmarks — confidence: {r['cap_confidence']}", bold=True)
    _put(rates, f"C{er}", ev["why"], wrap=False)
    for i, p in enumerate(ev["points"]):
        _put(rates, f"A{er + 1 + i}", f"{p[1]}, Q{p[3]} {p[2]}")
        _put(rates, f"B{er + 1 + i}", p[0], PCT2, color=BLUE)
    rates.column_dimensions["A"].width = 44
    rates.column_dimensions["B"].width = 12
    rates.column_dimensions["C"].width = 80

    # ------------------------------------------------------------------ Summary inputs (rows fixed)
    _title(ws, f"{title} — underwriting summary",
           "Automated estimate for information only — not an appraisal or broker opinion of value.")
    _put(ws, "A4", "Key assumptions", bold=True)
    assumptions = [  # row 5 onward
        ("Going-in cap rate", r["cap_rate"], PCT2, BLUE, f"Confidence: {r['cap_confidence']}. {ev['label']}"),   # 5
        ("Exit cap rate (year-10 sale)", r["exit_cap"], PCT2, BLUE, r["sources"]["Exit cap"]),                     # 6
        ("Selling costs at exit", md.SELLING_COSTS, PCT, BLUE, "Standard assumption"),                             # 7
        ("Year 11 NOI (basis for sale price)", r["year11_noi"], MONEY, BLUE, "Cash flow model, year 11"),          # 8
        ("Discount rate", f"=Rates!B{drow}", PCT2, GREEN, "Build-up on the Rates sheet"),                          # 9
        ("Stabilized NOI (today's dollars)", r["stabilized_noi"]["noi"], MONEY, BLUE, "NOI at stabilized occupancy"),  # 10
        ("Lease-up costs + lost rent", r["leaseup_cost"] + r["lost_rent"], MONEY, BLUE, "Lease-up model"),          # 11
        ("Near-term repairs", r["one_time"], MONEY, BLUE, "Owner-provided"),                                         # 12
        ("Lease-up risk allowance", r["allowance"], MONEY, BLUE, "15% of lease-up costs + lost rent"),             # 13
        ("Sales comparison value", r["sales_value"] or 0, MONEY, BLUE, "Owner comps, class-adjusted median"),       # 14
        ("Weight: direct capitalization", r["weights"]["dc"] / 100, PCT, BLUE, "See reasons below"),               # 15
        ("Weight: discounted cash flow", r["weights"]["dcf"] / 100, PCT, BLUE, "See reasons below"),               # 16
        ("Weight: sales comparison", r["weights"]["sales"] / 100, PCT, BLUE, "See reasons below"),                 # 17
    ]
    for i, (label, val, fmt, color, note) in enumerate(assumptions):
        rr = 5 + i
        _put(ws, f"A{rr}", label)
        _put(ws, f"B{rr}", val, fmt, color=color, comment=f"Source: {note}",
             fill=KEY_FILL if rr in (5, 15, 16, 17) else None)

    # ------------------------------------------------------------------ Cash Flow
    _title(cf, f"{title} — 10-year cash flow", "Blue = model output used as input; black = formula. Negatives are costs.")
    _put(cf, "A4", "Line", bold=True)
    for i in range(years):
        _put(cf, f"{get_column_letter(i + 2)}4", f"Year {i + 1}", bold=True)
    _put(cf, "A5", "Year number")
    for i in range(years):
        _put(cf, f"{get_column_letter(i + 2)}5", i + 1, "0")
    row_of, row = {}, 6
    for label, key in CF_LINES:
        row_of[key] = row
        _put(cf, f"A{row}", label)
        for i, flow in enumerate(r["flows"]):
            _put(cf, f"{get_column_letter(i + 2)}{row}", flow[key], PCT if key == "occupancy" else MONEY, color=BLUE)
        row += 1
        if key == "recoveries":
            row_of["egi"] = row
            _put(cf, f"A{row}", "Effective gross income", bold=True)
            for i in range(years):
                c = get_column_letter(i + 2)
                _put(cf, f"{c}{row}", f"=SUM({c}{row_of['potential_rent']}:{c}{row_of['recoveries']})", MONEY, bold=True)
            row += 1
        if key == "taxes":
            row_of["noi"] = row
            _put(cf, f"A{row}", "Net operating income", bold=True)
            for i in range(years):
                c = get_column_letter(i + 2)
                _put(cf, f"{c}{row}", f"={c}{row_of['egi']}+SUM({c}{row_of['opex']}:{c}{row_of['taxes']})", MONEY, bold=True)
            row += 1
        if key == "one_time":
            row_of["cash_flow"] = row
            _put(cf, f"A{row}", "Cash flow", bold=True)
            for i in range(years):
                c = get_column_letter(i + 2)
                _put(cf, f"{c}{row}", f"={c}{row_of['noi']}+{c}{row_of['leasing_costs']}+{c}{row_of['one_time']}",
                     MONEY, bold=True)
            row += 1
    row += 1
    df_row, pv_row = row, row + 1
    _put(cf, f"A{df_row}", "Discount factor")
    _put(cf, f"A{pv_row}", "Present value of cash flow", bold=True)
    for i in range(years):
        c = get_column_letter(i + 2)
        _put(cf, f"{c}{df_row}", f"=1/(1+Summary!$B$9)^{c}$5", "0.0000")
        _put(cf, f"{c}{pv_row}", f"={c}{row_of['cash_flow']}*{c}{df_row}", MONEY, bold=True)
    for col in range(1, years + 2):
        cf.column_dimensions[get_column_letter(col)].width = 38 if col == 1 else 13
    cf.freeze_panes = "B6"
    cfr = row_of["cash_flow"]

    # ------------------------------------------------------------------ Summary valuation
    _put(ws, "A19", "Valuation", bold=True)
    calc = [
        ("PV of 10 years of cash flow", f"=SUM('Cash Flow'!B{pv_row}:{last}{pv_row})"),   # 20
        ("Sale at end of year 10 (net)", "=B8/B6*(1-B7)"),                                 # 21
        ("PV of sale", f"=B21/(1+B9)^{years}"),                                            # 22
        ("Discounted cash flow value", "=B20+B22-B13"),                                    # 23
        ("Direct capitalization value", "=B10/B5-B11-B12-B13"),                            # 24
        ("Sales comparison value", "=B14"),                                                # 25
        ("Estimated value (weighted)", "=IF(SUM(B15:B17)=0,0,(B15*B24+B16*B23+B17*B25)/SUM(B15:B17))"),  # 26
        ("Per " + ("unit" if r["sector"] == "multifamily" else "SF"), f"=B26/{r['size']}"),            # 27
    ]
    for i, (label, formula) in enumerate(calc):
        rr = 20 + i
        bold = "Estimated" in label
        _put(ws, f"A{rr}", label, bold=bold)
        _put(ws, f"B{rr}", formula, MONEY, bold=bold, fill="FFF2CC" if bold else None)

    _put(ws, "A29", "Why these weights", bold=True)
    for i, reason in enumerate(r["weight_reasons"]):
        _put(ws, f"A{30 + i}", reason)
    rr = 31 + len(r["weight_reasons"])
    _put(ws, f"A{rr}", r["range_label"], bold=True)
    for i, (name, val) in enumerate(r["scenarios"].items()):
        _put(ws, f"A{rr + 1 + i}", name)
        _put(ws, f"B{rr + 1 + i}", val, MONEY, color=BLUE,
             comment="Full model re-run under each scenario. See Sources for definitions — not a statistical interval.")
    rr += 5
    _put(ws, f"A{rr}", "Current vs. stabilized NOI (one year, today's dollars)", bold=True)
    _put(ws, f"B{rr}", "Current", bold=True)
    _put(ws, f"C{rr}", "Stabilized", bold=True)
    noi_lines = [("Occupancy", "occupancy", PCT), ("Potential rent", "potential_rent", MONEY),
                 ("Vacancy", "vacancy", MONEY), ("Collection loss", "credit_loss", MONEY),
                 ("Other income", "other_income", MONEY), ("Expense reimbursements", "recoveries", MONEY),
                 ("Operating expenses", "opex", MONEY), ("Management", "management", MONEY),
                 ("Reserves", "reserves", MONEY), ("Unreimbursed expenses", "nonrecoverable", MONEY),
                 ("Property taxes", "taxes", MONEY)]
    first = rr + 1
    for i, (label, key, fmt) in enumerate(noi_lines):
        _put(ws, f"A{first + i}", label)
        _put(ws, f"B{first + i}", r["current_noi"][key], fmt, color=BLUE)
        _put(ws, f"C{first + i}", r["stabilized_noi"][key], fmt, color=BLUE)
    end = first + len(noi_lines)
    _put(ws, f"A{end}", "Net operating income", bold=True)
    for col in "BC":
        _put(ws, f"{col}{end}", f"=SUM({col}{first + 1}:{col}{end - 1})", MONEY, bold=True)
    _put(ws, f"A{end + 2}", "Owner inputs", bold=True)
    for i, (k, v) in enumerate(inputs):
        _put(ws, f"A{end + 3 + i}", k)
        _put(ws, f"B{end + 3 + i}", v, color=BLUE)
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18

    # ------------------------------------------------------------------ Sensitivity
    _title(sens, "Value sensitivity")
    sd = r["sens_disc_exit"]
    _put(sens, "A3", "1. DCF value — discount rate (rows) × exit cap rate (columns). Live formulas on the Cash Flow sheet.",
         bold=True)
    _put(sens, "A4", "Discount \\ Exit", bold=True)
    for j, x in enumerate(sd["exits"]):
        _put(sens, f"{get_column_letter(j + 2)}4", x, PCT2, bold=True, color=BLUE)
    cfrange = f"'Cash Flow'!$B${cfr}:${last}${cfr}"
    yrrange = f"'Cash Flow'!$B$5:${last}$5"
    for i, rowd in enumerate(sd["rows"]):
        rr = 5 + i
        _put(sens, f"A{rr}", rowd["disc"], PCT2, bold=True, color=BLUE)
        for j in range(len(sd["exits"])):
            c = get_column_letter(j + 2)
            _put(sens, f"{c}{rr}",
                 f"=SUMPRODUCT({cfrange}/(1+$A{rr})^{yrrange})+Summary!$B$8/{c}$4*(1-Summary!$B$7)/(1+$A{rr})^{years}"
                 f"-Summary!$B$13", MONEY)
    _put(sens, "A11", "2. Direct capitalization value by going-in cap rate (live)", bold=True)
    _put(sens, "A12", "Cap rate", bold=True)
    _put(sens, "B12", "Direct cap value", bold=True)
    for i, d in enumerate([-0.005, -0.0025, 0, 0.0025, 0.005]):
        _put(sens, f"A{13 + i}", f"=Summary!$B$5+({d})", PCT2, bold=True)
        _put(sens, f"B{13 + i}", f"=Summary!$B$10/A{13 + i}-Summary!$B$11-Summary!$B$12-Summary!$B$13", MONEY)
    _put(sens, "A19", "3. Reconciled value — going-in cap rate (rows) × rent growth (columns). STATIC: each cell is a "
                      "full model re-run, so it does not update if you edit this workbook.", bold=True)
    _put(sens, "A20", "Cap \\ Growth", bold=True)
    for j, g in enumerate(r["sensitivity"]["growths"]):
        _put(sens, f"{get_column_letter(j + 2)}20", g, PCT, bold=True)
    for i, rowd in enumerate(r["sensitivity"]["rows"]):
        _put(sens, f"A{21 + i}", rowd["cap"], PCT2, bold=True)
        for j, val in enumerate(rowd["values"]):
            _put(sens, f"{get_column_letter(j + 2)}{21 + i}", val, MONEY, color=BLUE)
    sens.column_dimensions["A"].width = 18
    for col in "BCDEF":
        sens.column_dimensions[col].width = 16

    # ------------------------------------------------------------------ Lease schedule
    if leases is not None:
        L = r["leasing_assumptions"]
        _title(leases, "Lease rollover schedule (probability-weighted in the cash flow)",
               f"Renewal {L['renewal_prob']:.0%} · downtime {L['downtime']:.0f} mo · TI new ${L['ti_new']:.0f}/SF, "
               f"renewal ${L['ti_renew']:.0f}/SF · LC {L['lc_new']:.0%}/{L['lc_renew']:.0%} · "
               f"{L['term']:.0f}-yr terms · {L['bump']:.1%} bumps")
        for j, h in enumerate(["Suite", "Tenant", "Month of event", "Event", "Current rent $/SF"]):
            _put(leases, f"{get_column_letter(j + 1)}4", h, bold=True)
        for i, e in enumerate(sorted(r["lease_events"], key=lambda e: e["event_month"])):
            vals = [e["suite"], e["tenant"], e["event_month"], e["event"], e["rent_psf"]]
            for j, v in enumerate(vals):
                _put(leases, f"{get_column_letter(j + 1)}{5 + i}", v, '$#,##0.00' if j == 4 else None, color=BLUE)
        for col, wd in zip("ABCDE", (14, 28, 16, 52, 18)):
            leases.column_dimensions[col].width = wd

    # ------------------------------------------------------------------ Data check + sources
    _title(src, "Sources, assumptions and data check")
    rr = 3
    for k, v in r["sources"].items():
        _put(src, f"A{rr}", k, bold=True)
        _put(src, f"B{rr}", v, wrap=True)
        rr += 1
    rr += 1
    _put(src, f"A{rr}", "Model notes", bold=True)
    for n in r["notes"] + r["warnings"]:
        rr += 1
        _put(src, f"B{rr}", n, wrap=True)
    src.column_dimensions["A"].width = 28
    src.column_dimensions["B"].width = 110

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
