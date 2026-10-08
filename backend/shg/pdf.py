"""
Print-friendly PDF report (black text, thin grey lines, no coloured fills), so it prints
cleanly on an ordinary inkjet printer.
"""
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import Transaction

T = Transaction.Type
GREY = colors.HexColor("#9ca3af")
LIGHT = colors.HexColor("#d1d5db")


def rwf(n):
    return f"{int(n or 0):,}"


def _table(data, widths, number_cols=(), total_row=False, header_rows=1):
    t = Table(data, colWidths=widths, repeatRows=header_rows)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
        ("FONT", (0, 0), (-1, header_rows - 1), "Helvetica-Bold", 8),
        ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.8, colors.black),
        ("LINEBELOW", (0, header_rows), (-1, -1), 0.25, LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for c in number_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if total_row:
        style += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8.5),
                  ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]
    t.setStyle(TableStyle(style))
    return t


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#4b5563"))
    canvas.drawString(15 * mm, 8 * mm, doc.footer_text)
    canvas.drawRightString(doc.pagesize[0] - 15 * mm, 8 * mm, f"Urupapuro (Page) {doc.page}")
    canvas.restoreState()


def build_pdf(summary, title, generated_by):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=15 * mm, title=title)
    doc.footer_text = f"SHG system - {title} - {timezone.localtime():%d/%m/%Y %H:%M} - {generated_by}"

    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=16, alignment=0, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, textColor=colors.HexColor("#374151"))
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11, spaceBefore=10, spaceAfter=4)

    tot = summary["totals"]
    loans = summary["loans"]
    multi = len(summary["groups"]) > 1
    story = [
        Paragraph(title, h1),
        Paragraph(f"Igihe (Period): <b>{summary['period']['label']}</b> &nbsp;&nbsp; "
                  f"{summary['period']['start']:%d/%m/%Y} - {summary['period']['end']:%d/%m/%Y}", sub),
        Spacer(1, 6),
        Paragraph("Incamake (Summary)", h2),
    ]

    rows = [
        ["Imigabane (Shares bought)", rwf(tot[T.SHARE]), "Inguzanyo zatanzwe (Loans given)", rwf(tot[T.LOAN_ISSUE])],
        ["Ingoboka (Social fund in)", rwf(tot[T.INGOBOKA_IN]), "Ayishyuwe (Loans returned)", rwf(tot[T.LOAN_RETURN])],
        ["Ingoboka yatanzwe (Social fund paid out)", rwf(tot[T.INGOBOKA_OUT]), "Inyungu (Interest paid)", rwf(tot[T.INTEREST])],
        ["Mituweli (Mutuelle)", rwf(tot[T.MUTUELLE]), "Ibihano (Fines paid)", rwf(tot[T.FINE_PAYMENT])],
        ["Amafaranga yakoreshejwe (Expenses)", rwf(tot[T.EXPENSE]), "Imigabane yose kugeza ubu (Shares to date)", rwf(summary["savings_to_date"])],
        ["Inguzanyo zitarishyurwa (Loans still owed, today)", rwf(loans["outstanding"]),
         "Izarengeje igihe (Overdue, today)", f"{loans['overdue_count']} - {rwf(loans['overdue_amount'])}"],
    ]
    t = Table(rows, colWidths=[78 * mm, 38 * mm, 88 * mm, 38 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 9),
        ("FONT", (3, 0), (3, -1), "Helvetica-Bold", 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)

    # ---- Cash: what came in, what went out, what went to the bank, what is left in hand ----
    cash = summary.get("cash")
    if cash:
        P, D = cash["period"], cash["to_date"]
        story.append(Paragraph("Imari y'itsinda (Group cash) - muri iki gihe (this period) / kugeza ubu (up to the end date)", h2))
        lines = [["", "Muri iki gihe", "Kugeza ubu"]]
        names_in = [(T.SHARE, "Imigabane (Shares)"), (T.INGOBOKA_IN, "Ingoboka (Social fund)"),
                    (T.FINE_PAYMENT, "Ibihano (Fines)"), (T.INTEREST, "Inyungu (Interest)"),
                    (T.LOAN_RETURN, "Ayishyuwe (Loans returned)"), (T.OTHER_INCOME, "Andi mafaranga yinjiye (Other money in)")]
        names_out = [(T.LOAN_ISSUE, "Inguzanyo zatanzwe (Loans given)"), (T.INGOBOKA_OUT, "Ingoboka yatanzwe (Social fund paid out)"),
                     (T.EXPENSE, "Ibyakoreshejwe (Money spent)")]
        for k, label in names_in:
            lines.append(["+ " + label, rwf(P["in"][k]), rwf(D["in"][k])])
        lines.append(["Byinjiye byose (Total in)", rwf(P["total_in"]), rwf(D["total_in"])])
        for k, label in names_out:
            lines.append(["- " + label, rwf(P["out"][k]), rwf(D["out"][k])])
        lines.append(["Byasohotse byose (Total out)", rwf(P["total_out"]), rwf(D["total_out"])])
        lines.append(["Igiteranyo (In minus out)", rwf(P["net"]), rwf(D["net"])])
        lines.append(["- Byajyanywe kuri banki (Taken to the bank)", rwf(P["bank_deposits"]), rwf(D["bank_deposits"])])
        lines.append(["Asigaye mu ntoki (Cash still in hand)", rwf(P["in_hand"]), rwf(D["in_hand"])])
        lines.append(["Mituweli ibitswe ukwayo (Mutuelle, kept apart)", rwf(P["mutuelle"]), rwf(D["mutuelle"])])
        ct = Table(lines, colWidths=[120 * mm, 40 * mm, 40 * mm], repeatRows=1)
        bold_rows = [7, 11, 12, 14]
        style = [
            ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, LIGHT),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BOX", (0, 14), (-1, 14), 0.9, colors.black),
            ("FONT", (0, 15), (-1, 15), "Helvetica-Oblique", 8),
        ]
        style += [("FONT", (0, r), (-1, r), "Helvetica-Bold", 8.5) for r in bold_rows]
        ct.setStyle(TableStyle(style))
        story.append(ct)

        moves = [e for e in cash["entries"] if e["type"] in (T.OTHER_INCOME, T.EXPENSE, T.BANK_DEPOSIT)]
        if moves:
            story.append(Paragraph("Andi mafaranga yinjiye, ayakoreshejwe n'ayajyanywe kuri banki (Other money, spending and bank)", h2))
            data = [["Itariki (Date)"] + (["Itsinda"] if multi else []) +
                    ["Ubwoko (Type)", "Ibisobanuro (Details)", "Uwayajyanye (Taken by)", "Amafaranga"]]
            kinds = {T.OTHER_INCOME: "Yinjiye (In)", T.EXPENSE: "Yakoreshejwe (Spent)", T.BANK_DEPOSIT: "Banki (Bank)"}
            for e in moves:
                data.append([f"{e['date']:%d/%m/%Y}"] + ([e["shg_name"]] if multi else []) +
                            [kinds[e["type"]], e["description"][:60], e["carried_by"], rwf(e["amount"])])
            widths = [24 * mm] + ([30 * mm] if multi else []) + [30 * mm, 90 * mm, 45 * mm, 28 * mm]
            story.append(_table(data, widths, number_cols=(len(widths) - 1,)))

    if multi:
        story.append(Paragraph("Amatsinda (Groups)", h2))
        data = [["Itsinda (Group)", "Abanyamuryango", "Imigabane", "Ingoboka", "Mituweli",
                 "Ibihano", "Inyungu", "Inguzanyo", "Ayishyuwe"]]
        for g in summary["by_group"]:
            gt = g["totals"]
            data.append([g["name"], g["members"], rwf(gt[T.SHARE]), rwf(gt[T.INGOBOKA_IN]), rwf(gt[T.MUTUELLE]),
                         rwf(gt[T.FINE_PAYMENT]), rwf(gt[T.INTEREST]), rwf(gt[T.LOAN_ISSUE]), rwf(gt[T.LOAN_RETURN])])
        data.append(["Byose (Total)", sum(g["members"] for g in summary["by_group"]), rwf(tot[T.SHARE]),
                     rwf(tot[T.INGOBOKA_IN]), rwf(tot[T.MUTUELLE]), rwf(tot[T.FINE_PAYMENT]),
                     rwf(tot[T.INTEREST]), rwf(tot[T.LOAN_ISSUE]), rwf(tot[T.LOAN_RETURN])])
        story.append(_table(data, [60 * mm] + [26 * mm] * 8, number_cols=range(1, 9), total_row=True))

    story.append(Paragraph("Abanyamuryango (Members)", h2))
    head = ["#", "Nomero", "Izina (Name)"] + (["Itsinda"] if multi else []) + [
        "Imigabane\n(count)", "Imigabane\n(RWF)", "Ingoboka", "Mituweli", "Ibihano", "Inyungu",
        "Inguzanyo\n(given)", "Ayishyuwe\n(returned)", "Imigabane\nkugeza ubu"]
    data = [head]
    sums = {k: 0 for k in ("shares", T.SHARE, T.INGOBOKA_IN, T.MUTUELLE, T.FINE_PAYMENT, T.INTEREST,
                           T.LOAN_ISSUE, T.LOAN_RETURN, "shares_to_date")}
    for i, m in enumerate(summary["members"], 1):
        row = [i, m["member_code"], m["full_name"]] + ([m["shg_name"]] if multi else [])
        row += [m["shares"], rwf(m[T.SHARE]), rwf(m[T.INGOBOKA_IN]), rwf(m[T.MUTUELLE]), rwf(m[T.FINE_PAYMENT]),
                rwf(m[T.INTEREST]), rwf(m[T.LOAN_ISSUE]), rwf(m[T.LOAN_RETURN]), m["shares_to_date"]]
        for k in sums:
            sums[k] += m[k]
        data.append(row)
    data.append(["", "", "Byose (Total)"] + ([""] if multi else []) + [
        sums["shares"], rwf(sums[T.SHARE]), rwf(sums[T.INGOBOKA_IN]), rwf(sums[T.MUTUELLE]),
        rwf(sums[T.FINE_PAYMENT]), rwf(sums[T.INTEREST]), rwf(sums[T.LOAN_ISSUE]), rwf(sums[T.LOAN_RETURN]),
        sums["shares_to_date"]])
    name_w = 52 * mm if multi else 70 * mm
    widths = [8 * mm, 24 * mm, name_w] + ([30 * mm] if multi else []) + [19 * mm] * 9
    first_num = 4 if multi else 3
    story.append(_table(data, widths, number_cols=range(first_num, first_num + 9), total_row=True))

    if loans["overdue_list"]:
        story.append(Paragraph("Inguzanyo zarengeje igihe (Overdue loans, today)", h2))
        data = [["Izina (Name)"] + (["Itsinda"] if multi else []) + ["Inguzanyo", "Asigaye (Still owed)", "Itariki ntarengwa (Due)"]]
        for l in loans["overdue_list"]:
            data.append([l["member"]] + ([l["shg_name"]] if multi else []) +
                        [rwf(l["principal"]), rwf(l["outstanding"]), f"{l['due_date']:%d/%m/%Y}"])
        widths = [70 * mm] + ([40 * mm] if multi else []) + [35 * mm, 40 * mm, 40 * mm]
        story.append(_table(data, widths, number_cols=(len(widths) - 3, len(widths) - 2)))

    # ---- Signatures: who prepared the report, and space for whoever checks it ----
    story.append(Spacer(1, 18))
    sign = Table([
        ["Byakozwe na (Prepared by):", generated_by, "Byemejwe na (Checked by):", ""],
        ["Umukono (Signature):", "", "Umukono (Signature):", ""],
        ["Itariki (Date):", f"{timezone.localdate():%d/%m/%Y}", "Itariki (Date):", ""],
    ], colWidths=[52 * mm, 68 * mm, 52 * mm, 68 * mm], rowHeights=[9 * mm, 14 * mm, 9 * mm])
    sign.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9), ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 9),
        ("LINEBELOW", (1, 0), (1, -1), 0.6, colors.black), ("LINEBELOW", (3, 0), (3, -1), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    story.append(sign)

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()