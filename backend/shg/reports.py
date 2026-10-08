"""
Figures for dashboards and PDF reports. Everything is calculated from the ledger;
nothing here is stored.

A "period" is a year, optionally narrowed to one month (the old sheet's monthly tabs).
"""
import calendar
from datetime import date

from django.db.models import Count
from django.db.models.functions import ExtractMonth
from django.utils import timezone

from .models import Loan, Member, Transaction, signed_sum

T = Transaction.Type
MONEY_TYPES = [T.SHARE, T.INGOBOKA_IN, T.INGOBOKA_OUT, T.MUTUELLE, T.FINE_PAYMENT,
               T.LOAN_ISSUE, T.LOAN_RETURN, T.INTEREST, T.EXPENSE, T.OTHER_INCOME, T.BANK_DEPOSIT]

# The group's cash: what came in minus what went out. Mutuelle is kept apart because it is
# members' health-insurance money held for them, not the group's own money.
CASH_IN = [T.SHARE, T.INGOBOKA_IN, T.FINE_PAYMENT, T.INTEREST, T.LOAN_RETURN, T.OTHER_INCOME]
CASH_OUT = [T.LOAN_ISSUE, T.INGOBOKA_OUT, T.EXPENSE]

MONTHS_RW = ["Mutarama", "Gashyantare", "Werurwe", "Mata", "Gicurasi", "Kamena",
             "Nyakanga", "Kanama", "Nzeri", "Ukwakira", "Ugushyingo", "Ukuboza"]


def period_label(year, month, date_from=None, date_to=None):
    if date_from or date_to:
        a = f"{date_from:%d/%m/%Y}" if date_from else "..."
        b = f"{date_to:%d/%m/%Y}" if date_to else "..."
        return f"{a} - {b}"
    if month:
        return f"{MONTHS_RW[month - 1]} ({calendar.month_name[month]}) {year}"
    return str(year)


def period_bounds(year, month, date_from=None, date_to=None):
    if date_from or date_to:
        return date_from or date(2000, 1, 1), date_to or date(2100, 12, 31)
    if month:
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    return date(year, 1, 1), date(year, 12, 31)


def cash_position(ledger, start, end):
    """Money in, money out and cash in hand, for the period and everything up to its end."""
    def block(qs):
        t = qs.totals_by_type()
        money_in = {k: t.get(k, 0) for k in CASH_IN}
        money_out = {k: t.get(k, 0) for k in CASH_OUT}
        net = sum(money_in.values()) - sum(money_out.values())
        deposits = t.get(T.BANK_DEPOSIT, 0)
        return {"in": money_in, "out": money_out, "total_in": sum(money_in.values()),
                "total_out": sum(money_out.values()), "net": net, "bank_deposits": deposits,
                "in_hand": net - deposits, "mutuelle": t.get(T.MUTUELLE, 0)}

    entries = (ledger.filter(date__gte=start, date__lte=end,
                             type__in=[T.OTHER_INCOME, T.EXPENSE, T.BANK_DEPOSIT, T.INGOBOKA_OUT],
                             is_reversal=False, reversed_by__isnull=True)
               .select_related("shg", "member", "recorded_by").order_by("-date", "-id"))
    return {
        "period": block(ledger.filter(date__gte=start, date__lte=end)),
        "to_date": block(ledger.filter(date__lte=end)),
        "entries": [
            {"id": e.id, "date": e.date, "type": e.type, "type_display": e.get_type_display(),
             "amount": e.amount, "description": e.description, "carried_by": e.carried_by,
             "expense_category": e.expense_category, "shg": e.shg_id, "shg_name": e.shg.name,
             "member": e.member.full_name if e.member else "", "recorded_by": str(e.recorded_by)}
            for e in entries[:200]
        ],
    }


def _empty():
    return {t: 0 for t in MONEY_TYPES}


def build_summary(groups, year, month=None, date_from=None, date_to=None):
    """
    groups: queryset of SHG the user may see (already scoped).
    Returns totals for the period, per group, per member, a 12-month series for the year,
    and the loan position today.
    """
    start, end = period_bounds(year, month, date_from, date_to)
    group_ids = list(groups.values_list("id", flat=True))
    ledger = Transaction.objects.filter(shg_id__in=group_ids)
    in_period = ledger.filter(date__gte=start, date__lte=end)

    totals = _empty()
    totals.update(in_period.totals_by_type())

    by_group = {g.id: {"id": g.id, "code": g.code, "name": g.name, "totals": _empty(), "members": 0}
                for g in groups.order_by("name")}
    for r in in_period.order_by().values("shg", "type").annotate(v=signed_sum("amount")):
        by_group[r["shg"]]["totals"][r["type"]] = r["v"]
    for r in Member.objects.filter(shg_id__in=group_ids, status=Member.Status.ACTIVE).order_by() \
            .values("shg").annotate(n=Count("id")):
        by_group[r["shg"]]["members"] = r["n"]

    # Per member, for the period, plus shares owned to the end of the period.
    members = {}
    qs = Member.objects.filter(shg_id__in=group_ids).select_related("shg").order_by("shg__name", "last_name", "first_name")
    for m in qs:
        members[m.id] = {"id": m.id, "member_code": m.member_code, "full_name": m.full_name,
                         "shg": m.shg_id, "shg_name": m.shg.name, "status": m.status,
                         "shares": 0, "shares_to_date": 0, **_empty()}
    for r in in_period.exclude(member=None).order_by().values("member", "type").annotate(
            v=signed_sum("amount"), n=signed_sum("share_count")):
        row = members.get(r["member"])
        if row:
            row[r["type"]] = r["v"]
            if r["type"] == T.SHARE:
                row["shares"] = r["n"]
    for r in ledger.filter(type=T.SHARE, date__lte=end).exclude(member=None).order_by() \
            .values("member").annotate(n=signed_sum("share_count")):
        if r["member"] in members:
            members[r["member"]]["shares_to_date"] = r["n"]
    member_rows = [m for m in members.values()
                   if m["status"] == Member.Status.ACTIVE or any(m[t] for t in MONEY_TYPES)]

    # 12-month series for the chart (always the whole year, so the chosen month can be highlighted).
    monthly = [{"month": i, "label": MONTHS_RW[i - 1][:3], **_empty()} for i in range(1, 13)]
    year_ledger = ledger.filter(date__year=year).annotate(m=ExtractMonth("date"))
    for r in year_ledger.order_by().values("m", "type").annotate(v=signed_sum("amount")):
        monthly[r["m"] - 1][r["type"]] = r["v"]

    # Loans as they stand today (not limited to the period).
    today = timezone.localdate()
    open_loans = list(Loan.objects.filter(shg_id__in=group_ids).open().select_related("member", "shg"))
    overdue = [l for l in open_loans if l.due_date < today]
    loans = {
        "open_count": len(open_loans),
        "outstanding": sum(l.outstanding_total for l in open_loans),
        "overdue_count": len(overdue),
        "overdue_amount": sum(l.outstanding_total for l in overdue),
        "overdue_list": [
            {"id": l.id, "member": l.member.full_name, "shg_name": l.shg.name, "principal": l.principal,
             "outstanding": l.outstanding_total, "due_date": l.due_date}
            for l in sorted(overdue, key=lambda x: x.due_date)
        ],
    }

    savings_to_date = ledger.filter(type=T.SHARE, date__lte=end).total()

    return {
        "period": {"year": year, "month": month, "label": period_label(year, month, date_from, date_to),
                   "start": start, "end": end, "date_from": date_from, "date_to": date_to},
        "groups": [{"id": g["id"], "code": g["code"], "name": g["name"]} for g in by_group.values()],
        "totals": totals,
        "savings_to_date": savings_to_date,
        "by_group": list(by_group.values()),
        "members": member_rows,
        "monthly": monthly,
        "loans": loans,
        "cash": cash_position(ledger, start, end),
    }