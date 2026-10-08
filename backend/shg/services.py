"""
Business operations that touch several tables at once.

Every function here is atomic: it saves everything or nothing.
Views call these; they never build Transactions themselves.
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction as db
from django.db.models import Q
from django.utils import timezone

from .models import (Attendance, AuditLog, Cycle, Fine, Loan, Meeting, MeetingSubmission, Member,
                     PeriodClosing, Transaction, signed_sum)

T = Transaction.Type


def error_list(exc: ValidationError):
    """Turn a Django ValidationError into short readable strings."""
    if hasattr(exc, "message_dict"):
        out = []
        for field, msgs in exc.message_dict.items():
            for m in msgs:
                out.append(m if field == "__all__" else f"{field}: {m}")
        return out
    return list(exc.messages)


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------
@db.atomic
def issue_loan(*, shg, member, principal, issue_date, user, meeting=None, purpose="", over_limit_reason=""):
    cycle = Cycle.for_date(shg, issue_date)
    loan = Loan(shg=shg, cycle=cycle, member=member, principal=principal, issue_date=issue_date,
                meeting=meeting, purpose=purpose, recorded_by=user)
    if over_limit_reason:
        loan.over_limit_approved_by = user
        loan.over_limit_reason = over_limit_reason
    loan.full_clean()
    loan.save()

    cash_out = Transaction(shg=shg, cycle=cycle, meeting=meeting, member=member, date=issue_date,
                           type=T.LOAN_ISSUE, amount=principal, loan=loan, recorded_by=user,
                           description=(purpose or "")[:255])
    cash_out.full_clean()
    cash_out.save()

    changes = {"principal": principal, "member": member.member_code, "due_date": str(loan.due_date)}
    if over_limit_reason:
        changes["over_limit_reason"] = over_limit_reason
    AuditLog.record(user, AuditLog.Action.CREATE, loan, changes)
    return loan


@db.atomic
def cancel_loan(loan, user, reason):
    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if loan.cancelled_at:
        raise ValidationError("This loan is already cancelled.")
    if loan.returned or loan.interest_paid:
        raise ValidationError("This loan already has payments. Reverse those payments first.")
    issue = loan.transactions.filter(type=T.LOAN_ISSUE, is_reversal=False, reversed_by__isnull=True).first()
    if issue:
        issue.reverse(user, f"Loan cancelled: {reason}", allow_loan_issue=True)
    loan.cancelled_at = timezone.now()
    loan.cancel_reason = reason[:255]
    loan.save(update_fields=["cancelled_at", "cancel_reason", "updated_at"])
    AuditLog.record(user, AuditLog.Action.UPDATE, loan, {"cancelled": True, "reason": reason})
    return loan


# ---------------------------------------------------------------------------
# Weekly meeting sheet
# ---------------------------------------------------------------------------
def _loan_row(loan, today):
    return {
        "id": loan.id,
        "principal": loan.principal,
        "issue_date": loan.issue_date,
        "due_date": loan.due_date,
        "returned": loan.returned_total,
        "interest_paid": loan.interest_total,
        "outstanding": loan.outstanding_total,
        "interest_due_on_full_return": int(loan.principal * loan.interest_rate_percent / 100),
        "status": Loan.compute_status(due_date=loan.due_date, outstanding=loan.outstanding_total,
                                      returned=loan.returned_total, cancelled_at=loan.cancelled_at, today=today),
    }


def build_meeting_sheet(meeting: Meeting):
    """
    Everything the leader's weekly screen needs, in one response:
    every active member (plus anyone with an open loan or an entry at this meeting),
    what is already recorded at this meeting, their year-to-date totals,
    open loans and unpaid fines.
    """
    shg, cycle = meeting.shg, meeting.cycle
    today = timezone.localdate()

    open_loans = list(Loan.objects.filter(shg=shg).open().order_by("issue_date"))
    unpaid_fines = list(Fine.objects.filter(shg=shg).unpaid().order_by("issued_date"))
    loan_members = {l.member_id for l in open_loans}

    members = (
        Member.objects.filter(shg=shg)
        .filter(Q(status=Member.Status.ACTIVE) | Q(pk__in=loan_members) | Q(transactions__meeting=meeting))
        .distinct()
        .order_by("last_name", "first_name")
    )

    def totals(qs):
        out = {}
        for r in qs.order_by().values("member", "type").annotate(v=signed_sum("amount"), n=signed_sum("share_count")):
            d = out.setdefault(r["member"], {})
            d[r["type"]] = r["v"]
            if r["type"] == T.SHARE:
                d["share_count"] = r["n"]
        return out

    at_meeting = totals(Transaction.objects.filter(meeting=meeting))
    to_date = totals(Transaction.objects.filter(cycle=cycle, date__lte=meeting.date))
    present = dict(Attendance.objects.filter(meeting=meeting).values_list("member_id", "present"))

    rows = []
    for m in members:
        now, ytd = at_meeting.get(m.id, {}), to_date.get(m.id, {})
        rows.append({
            "member": {"id": m.id, "member_code": m.member_code, "full_name": m.full_name, "status": m.status},
            "present": present.get(m.id),
            "recorded": {
                "shares": now.get("share_count", 0),
                "share_value": now.get(T.SHARE, 0),
                "ingoboka": now.get(T.INGOBOKA_IN, 0),
                "mutuelle": now.get(T.MUTUELLE, 0),
                "returned": now.get(T.LOAN_RETURN, 0),
                "interest": now.get(T.INTEREST, 0),
                "fines_paid": now.get(T.FINE_PAYMENT, 0),
                "loan_issued": now.get(T.LOAN_ISSUE, 0),
            },
            "to_date": {
                "shares": ytd.get("share_count", 0),
                "share_value": ytd.get(T.SHARE, 0),
                "ingoboka": ytd.get(T.INGOBOKA_IN, 0),
                "mutuelle": ytd.get(T.MUTUELLE, 0),
            },
            "open_loans": [_loan_row(l, today) for l in open_loans if l.member_id == m.id],
            "unpaid_fines": [
                {"id": f.id, "reason": f.reason, "reason_display": f.get_reason_display(), "amount": f.amount,
                 "paid": f.paid_total, "remaining": f.amount - f.paid_total, "issued_date": f.issued_date,
                 "loan": f.loan_id}
                for f in unpaid_fines if f.member_id == m.id
            ],
        })

    meeting_totals = Transaction.objects.filter(meeting=meeting).totals_by_type()
    return {
        "meeting": {"id": meeting.id, "shg": shg.id, "shg_code": shg.code, "shg_name": shg.name,
                    "date": meeting.date, "location": meeting.location, "notes": meeting.notes,
                    "is_closed": PeriodClosing.is_closed(shg.id, meeting.date)},
        "cycle": {"id": cycle.id, "name": cycle.name, "share_price": cycle.share_price,
                  "ingoboka_weekly": cycle.ingoboka_weekly, "mutuelle_weekly": cycle.mutuelle_weekly,
                  "interest_rate_percent": cycle.interest_rate_percent,
                  "loan_term_months": cycle.loan_term_months},
        "rows": rows,
        "meeting_totals": {k: meeting_totals.get(k, 0) for k in T.values},
        "submissions": meeting.submissions.count(),
    }


class _Rollback(Exception):
    pass


class SheetErrors(Exception):
    """Row-by-row errors from a weekly sheet: {"3": {"shares": ["..."]}}."""

    def __init__(self, errors):
        super().__init__("Weekly sheet has errors")
        self.errors = errors


def save_meeting_sheet(*, meeting: Meeting, user, submission_id, rows):
    """
    Save a whole weekly sheet in one transaction.

    rows: [{member, present, shares, ingoboka, mutuelle,
            loan_payments: [{loan, returned, interest}],
            fine_payments: [{fine, amount}],
            new_fines: [{reason, amount, note, loan, paid_now}]}]

    Values are ADDED to what is already recorded. If any row has an error,
    nothing is saved and every error is returned, keyed by row number.
    Re-sending the same submission_id returns the first result without saving again.
    """
    errors = {}
    counts = {"transactions": 0, "fines": 0}

    try:
        with db.atomic():
            existing = MeetingSubmission.objects.filter(submission_id=submission_id).first()
            if existing:
                if existing.meeting_id != meeting.id:
                    raise ValidationError({"submission_id": "This submission id was used for another meeting."})
                return existing, True

            if PeriodClosing.is_closed(meeting.shg_id, meeting.date):
                raise ValidationError({"meeting": "That month is closed. Ask the administrator."})
            if meeting.cycle.status != Cycle.Status.OPEN:
                raise ValidationError({"meeting": "This savings cycle is closed."})

            seen = set()
            for i, row in enumerate(rows):
                member = row["member"]
                row_errors = {}

                if member.id in seen:
                    errors[str(i)] = {"member": [f"{member.full_name} appears twice on the sheet."]}
                    continue
                seen.add(member.id)
                if member.shg_id != meeting.shg_id:
                    errors[str(i)] = {"member": ["This member belongs to another group."]}
                    continue

                def add(label, **fields):
                    tx = Transaction(shg=meeting.shg, cycle=meeting.cycle, meeting=meeting, member=member,
                                     date=meeting.date, recorded_by=user, **fields)
                    try:
                        tx.full_clean()
                        tx.save()
                        counts["transactions"] += 1
                    except ValidationError as exc:
                        row_errors.setdefault(label, []).extend(error_list(exc))

                if row.get("present") is not None:
                    Attendance.objects.update_or_create(meeting=meeting, member=member,
                                                        defaults={"present": row["present"]})
                if row.get("shares"):
                    add("shares", type=T.SHARE, share_count=row["shares"],
                        amount=row["shares"] * meeting.cycle.share_price)
                if row.get("ingoboka"):
                    add("ingoboka", type=T.INGOBOKA_IN, amount=row["ingoboka"])
                if row.get("mutuelle"):
                    add("mutuelle", type=T.MUTUELLE, amount=row["mutuelle"])

                for lp in row.get("loan_payments") or []:
                    if lp.get("interest"):
                        add("loan_payments", type=T.INTEREST, amount=lp["interest"], loan=lp["loan"])
                    if lp.get("returned"):
                        add("loan_payments", type=T.LOAN_RETURN, amount=lp["returned"], loan=lp["loan"])

                for fp in row.get("fine_payments") or []:
                    if fp.get("amount"):
                        add("fine_payments", type=T.FINE_PAYMENT, amount=fp["amount"], fine=fp["fine"])

                for nf in row.get("new_fines") or []:
                    fine = Fine(shg=meeting.shg, cycle=meeting.cycle, member=member, meeting=meeting,
                                loan=nf.get("loan"), reason=nf["reason"], reason_note=nf.get("note", ""),
                                amount=nf["amount"], issued_date=meeting.date, recorded_by=user)
                    try:
                        fine.full_clean()
                        fine.save()
                        counts["fines"] += 1
                    except ValidationError as exc:
                        row_errors.setdefault("new_fines", []).extend(error_list(exc))
                        continue
                    if nf.get("paid_now"):
                        add("new_fines", type=T.FINE_PAYMENT, amount=fine.amount, fine=fine)

                if row_errors:
                    errors[str(i)] = row_errors

            if errors:
                raise _Rollback

            submission = MeetingSubmission.objects.create(
                meeting=meeting, submission_id=submission_id, submitted_by=user,
                transaction_count=counts["transactions"], fine_count=counts["fines"],
            )
            AuditLog.record(user, AuditLog.Action.CREATE, meeting,
                            {"sheet_saved": str(submission_id), "transactions": counts["transactions"],
                             "fines": counts["fines"], "rows": len(rows)})
            return submission, False

    except _Rollback:
        raise SheetErrors(errors)
    except IntegrityError:
        # Two identical submissions arrived at the same moment; the other one won.
        existing = MeetingSubmission.objects.filter(submission_id=submission_id).first()
        if existing and existing.meeting_id == meeting.id:
            return existing, True
        raise


# ---------------------------------------------------------------------------
# Member dashboard
# ---------------------------------------------------------------------------
def member_summary(member: Member, cycle: Cycle):
    data = member.summary(cycle)
    data.update({
        "member": {"id": member.id, "member_code": member.member_code, "full_name": member.full_name,
                   "shg": member.shg_id, "status": member.status},
        "cycle": {"id": cycle.id, "name": cycle.name},
        "loan_limit": {
            "multiplier": cycle.loan_multiplier,
            "max_new_loan": member.max_new_loan(cycle),
            "group_lendable_cash": cycle.lendable_cash(),
        },
        "unpaid_fines": sum(f.amount - f.paid_total for f in Fine.objects.filter(member=member).unpaid()),
    })
    return data
