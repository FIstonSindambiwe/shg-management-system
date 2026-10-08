"""
shg/models.py — SHG Management & Financial Tracking System

Design rules this file enforces
--------------------------------
1. Money lives in ONE ledger (Transaction). Totals are always calculated,
   never typed in.
2. Transactions are never edited or deleted. A mistake is corrected with a
   reversal entry, so the history always shows what happened.
3. Nothing can be dated inside a closed month.
4. Loan status (Active / Partly returned / Overdue / Paid) is calculated from
   the due date and returned amounts, never stored.
5. A leader only sees their own group: every model with an `shg` field has
   `.objects.for_user(request.user)`. Use it in EVERY DRF get_queryset().

Amounts are whole Rwandan francs (no decimals).

Rules confirmed with the user
-----------------------------
- 1 share (imigabane) = 500 RWF; ingoboka 100/week; Mutuelle 500/week
- Loan interest 7%, loan must be returned within 3 months
- Interest may be paid before the 3 months are up
- Loan limit is based on the member's shares (multiplier per group: TO CONFIRM)
- Late-loan fines follow each group's own rules -> recorded, not auto-charged
- At year end, profit is shared out by shares

Still to confirm (marked TODO below)
------------------------------------
- loan multiplier per group
- whether fines join the year-end profit pool
- whether Ingoboka / Mutuelle money may be lent out
"""
import calendar
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction as db_transaction
from django.db.models import BigIntegerField, Case, F, OuterRef, Q, Subquery, Sum, When
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

USER = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def add_months(d: date, months: int) -> date:
    """14 Jan + 3 months -> 14 Apr; 30 Nov + 3 months -> 28/29 Feb."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def signed_sum(field, prefix="", extra=None):
    """SUM that counts reversal entries as negative."""
    p = f"{prefix}__" if prefix else ""
    base = extra if extra is not None else Q()
    return Coalesce(
        Sum(
            Case(
                When(base & Q(**{f"{p}is_reversal": False}), then=F(f"{p}{field}")),
                # Cast first: MySQL refuses to negate an UNSIGNED column (error 1690).
                When(base & Q(**{f"{p}is_reversal": True}),
                     then=Cast(F(f"{p}{field}"), BigIntegerField()) * -1),
                default=0,
                output_field=BigIntegerField(),
            )
        ),
        0,
        output_field=BigIntegerField(),
    )


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ScopedQuerySet(models.QuerySet):
    """Row-level security: leaders only get rows from their own group(s)."""

    shg_lookup = "shg"

    def for_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.can_see_all_groups:
            return self
        ids = LeaderAssignment.objects.filter(
            leader=user, end_date__isnull=True
        ).values("shg_id")
        return self.filter(**{f"{self.shg_lookup}__in": ids})


# ---------------------------------------------------------------------------
# Groups and leaders
# ---------------------------------------------------------------------------
class SHGQuerySet(ScopedQuerySet):
    shg_lookup = "pk"


class SHG(TimeStamped):
    """A Self-Help Group. Named SHG to avoid clashing with django.contrib.auth Group."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        SUSPENDED = "SUSPENDED", "Suspended"
        ARCHIVED = "ARCHIVED", "Archived"

    code = models.CharField(max_length=10, unique=True, help_text="e.g. SHG001")
    name = models.CharField(max_length=100, help_text="e.g. Amahoro")
    location = models.CharField(max_length=150, blank=True)
    formation_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    rules_note = models.TextField(
        blank=True,
        help_text="The group's own rules (e.g. late-loan fine). Shown, not enforced.",
    )

    objects = SHGQuerySet.as_manager()

    class Meta:
        ordering = ["code"]
        verbose_name = "Self-Help Group"

    def __str__(self):
        return f"{self.code} — {self.name}"

    @property
    def open_cycle(self):
        return self.cycles.filter(status=Cycle.Status.OPEN).first()

    @property
    def current_leader(self):
        a = self.leader_assignments.filter(end_date__isnull=True).select_related("leader").first()
        return a.leader if a else None


class LeaderAssignment(models.Model):
    """History of who led which group. Changing leader = end one row, start another."""

    shg = models.ForeignKey(SHG, on_delete=models.PROTECT, related_name="leader_assignments")
    leader = models.ForeignKey(
        USER,
        on_delete=models.PROTECT,
        related_name="leader_assignments",
        limit_choices_to={"role": "LEADER"},
    )
    start_date = models.DateField(default=date.today)
    end_date = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = ScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date"]

    def clean(self):
        # MySQL ignores partial unique constraints, so this is enforced here.
        if self.end_date is None:
            clash = LeaderAssignment.objects.filter(shg=self.shg_id, end_date__isnull=True)
            if clash.exclude(pk=self.pk).exists():
                raise ValidationError("This group already has an active leader. End that assignment first.")
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError("End date cannot be before start date.")


# ---------------------------------------------------------------------------
# Cycle (savings year) — invisible to leaders, set automatically
# ---------------------------------------------------------------------------
class Cycle(TimeStamped):
    """
    One savings year per group. Rules are stored per cycle so that changing
    next year's rules never rewrites last year's share-out.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed (shared out)"

    shg = models.ForeignKey(SHG, on_delete=models.PROTECT, related_name="cycles")
    name = models.CharField(max_length=30, help_text="e.g. 2026")
    start_date = models.DateField()
    end_date = models.DateField()

    share_price = models.PositiveIntegerField(default=500)
    ingoboka_weekly = models.PositiveIntegerField(default=100)
    mutuelle_weekly = models.PositiveIntegerField(default=500)
    interest_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=7)
    loan_term_months = models.PositiveSmallIntegerField(default=3)
    # TODO confirm per group: 1x, 2x or 3x the member's share value
    loan_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1)
    # TODO confirm: do fines go into the year-end profit pool?
    fines_in_profit = models.BooleanField(default=True)
    opening_cash = models.BigIntegerField(
        default=0, help_text="Lendable cash in the box when the cycle started (needed for imports)."
    )

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    objects = ScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date"]
        constraints = [models.UniqueConstraint(fields=["shg", "name"], name="uniq_cycle_name_per_shg")]

    def __str__(self):
        return f"{self.shg.code} {self.name}"

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError("Cycle end date must be after start date.")
        if self.status == self.Status.OPEN:
            others = Cycle.objects.filter(shg=self.shg_id, status=self.Status.OPEN).exclude(pk=self.pk)
            if others.exists():
                raise ValidationError("This group already has an open cycle.")

    def contains(self, d):
        return self.start_date <= d <= self.end_date

    @classmethod
    def for_date(cls, shg, d):
        """The open cycle covering a date. Leaders never pick a cycle; this does."""
        cycle = cls.objects.filter(shg=shg, status=cls.Status.OPEN, start_date__lte=d, end_date__gte=d).first()
        if not cycle:
            raise ValidationError({"date": f"{shg.code} has no open savings cycle covering {d:%d/%m/%Y}."})
        return cycle

    def ledger(self):
        return Transaction.objects.filter(cycle=self)

    def lendable_cash(self):
        """
        Cash the group can lend right now.
        TODO confirm: Ingoboka and Mutuelle are excluded on the assumption
        that they are not lent out.
        """
        T = Transaction.Type
        t = self.ledger().totals_by_type()
        cash_in = sum(t.get(k, 0) for k in (T.SHARE, T.LOAN_RETURN, T.INTEREST, T.FINE_PAYMENT, T.OTHER_INCOME))
        cash_out = t.get(T.LOAN_ISSUE, 0) + t.get(T.EXPENSE, 0)
        return self.opening_cash + cash_in - cash_out


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
class Member(TimeStamped):
    class Gender(models.TextChoices):
        FEMALE = "F", "Female"
        MALE = "M", "Male"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        LEFT = "LEFT", "Left group"
        SUSPENDED = "SUSPENDED", "Suspended"

    shg = models.ForeignKey(SHG, on_delete=models.PROTECT, related_name="members")
    member_code = models.CharField(max_length=20, unique=True, help_text="e.g. SHG001-M001")
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, db_index=True)
    date_joined = models.DateField(default=date.today)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)

    # From the "MITUELLE INFO" sheet
    national_id = models.CharField("Indangamuntu", max_length=16, blank=True)
    cell = models.CharField("Akagali", max_length=60, blank=True)
    sector = models.CharField("Umurenge", max_length=60, blank=True)
    is_household_head = models.BooleanField("Umukuru w'umuryango", default=False)
    household_size = models.PositiveSmallIntegerField("Abagize umuryango", null=True, blank=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        ordering = ["shg", "last_name", "first_name"]
        indexes = [models.Index(fields=["shg", "last_name"])]

    def __str__(self):
        return f"{self.member_code} {self.full_name}"

    @property
    def full_name(self):
        return f"{self.last_name.upper()} {self.first_name}"

    def shares(self, cycle):
        return Transaction.objects.filter(
            member=self, cycle=cycle, type=Transaction.Type.SHARE
        ).total("share_count")

    def share_value(self, cycle):
        return self.shares(cycle) * cycle.share_price

    def outstanding_principal(self, exclude_loan=None):
        loans = self.loans.filter(cancelled_at__isnull=True)
        if exclude_loan is not None and exclude_loan.pk:
            loans = loans.exclude(pk=exclude_loan.pk)
        return sum(loan.outstanding for loan in loans)

    def max_new_loan(self, cycle, exclude_loan=None):
        limit = int(self.share_value(cycle) * cycle.loan_multiplier)
        return max(0, limit - self.outstanding_principal(exclude_loan))

    def summary(self, cycle):
        """Everything the member dashboard needs, for one cycle."""
        T = Transaction.Type
        t = Transaction.objects.filter(member=self, cycle=cycle).totals_by_type()
        return {
            "shares": self.shares(cycle),
            "share_value": self.share_value(cycle),
            "ingoboka": t.get(T.INGOBOKA_IN, 0),
            "mutuelle": t.get(T.MUTUELLE, 0),
            "fines_paid": t.get(T.FINE_PAYMENT, 0),
            "borrowed": t.get(T.LOAN_ISSUE, 0),
            "returned": t.get(T.LOAN_RETURN, 0),
            "interest_paid": t.get(T.INTEREST, 0),
            "outstanding": self.outstanding_principal(),
        }


# ---------------------------------------------------------------------------
# Weekly meetings
# ---------------------------------------------------------------------------
class Meeting(TimeStamped):
    """The weekly gathering. Every entry the leader makes hangs off one."""

    shg = models.ForeignKey(SHG, on_delete=models.PROTECT, related_name="meetings")
    cycle = models.ForeignKey(Cycle, on_delete=models.PROTECT, related_name="meetings")
    date = models.DateField()
    location = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    objects = ScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-date"]
        constraints = [models.UniqueConstraint(fields=["shg", "date"], name="uniq_meeting_per_day")]

    def __str__(self):
        return f"{self.shg.code} {self.date:%d/%m/%Y}"

    def clean(self):
        if self.cycle.shg_id != self.shg_id:
            raise ValidationError("Cycle belongs to another group.")
        if not self.cycle.contains(self.date):
            raise ValidationError("Meeting date is outside the cycle.")
        if PeriodClosing.is_closed(self.shg_id, self.date):
            raise ValidationError({"date": "That month is closed."})


class MeetingSubmission(models.Model):
    """
    One saved weekly sheet. submission_id is generated by the app before sending,
    so if a leader taps Save twice on a slow connection, the second request is
    recognised and nothing is recorded twice.
    """

    meeting = models.ForeignKey("Meeting", on_delete=models.PROTECT, related_name="submissions")
    submission_id = models.UUIDField(unique=True)
    submitted_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    transaction_count = models.PositiveIntegerField(default=0)
    fine_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Attendance(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="attendance")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="attendance")
    present = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["meeting", "member"], name="uniq_attendance")]


# ---------------------------------------------------------------------------
# Loans (inguzanyo)
# ---------------------------------------------------------------------------
class LoanQuerySet(ScopedQuerySet):
    @staticmethod
    def _ledger_total(tx_type):
        # A subquery (not a JOIN + GROUP BY) so MySQL/MariaDB can filter on it
        # and so joining fines later can't double-count amounts.
        rows = (
            Transaction.objects.filter(loan=OuterRef("pk"), type=tx_type)
            .order_by().values("loan").annotate(v=signed_sum("amount")).values("v")
        )
        return Coalesce(Subquery(rows, output_field=BigIntegerField()), 0, output_field=BigIntegerField())

    def with_balances(self):
        T = Transaction.Type
        return self.annotate(
            returned_total=self._ledger_total(T.LOAN_RETURN),
            interest_total=self._ledger_total(T.INTEREST),
        ).annotate(outstanding_total=Cast(F("principal"), BigIntegerField()) - F("returned_total"))

    def open(self):
        return self.with_balances().filter(cancelled_at__isnull=True, outstanding_total__gt=0)

    def overdue(self, today=None):
        return self.open().filter(due_date__lt=today or timezone.localdate())

    def overdue_without_late_fine(self, today=None):
        """Admin report: late loans where the group recorded no late fine."""
        return self.overdue(today).exclude(
            fines__reason="LATE_LOAN", fines__cancelled_at__isnull=True
        )


class Loan(TimeStamped):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        PARTIAL = "PARTIAL", "Partly returned"
        OVERDUE = "OVERDUE", "Overdue"
        PAID = "PAID", "Fully returned"
        CANCELLED = "CANCELLED", "Cancelled"

    shg = models.ForeignKey(SHG, on_delete=models.PROTECT, related_name="loans")
    cycle = models.ForeignKey(Cycle, on_delete=models.PROTECT, related_name="loans")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="loans")
    meeting = models.ForeignKey(Meeting, null=True, blank=True, on_delete=models.PROTECT, related_name="loans")
    principal = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    interest_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    issue_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    purpose = models.CharField(max_length=200, blank=True)
    recorded_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    # Only an administrator may approve a loan above the member's limit.
    over_limit_approved_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    over_limit_reason = models.CharField(max_length=255, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    objects = LoanQuerySet.as_manager()

    class Meta:
        ordering = ["-issue_date"]
        indexes = [models.Index(fields=["shg", "due_date"])]

    def __str__(self):
        return f"L{self.pk} {self.member.full_name} {self.principal:,}"

    def save(self, *args, **kwargs):
        if self.interest_rate_percent is None:
            self.interest_rate_percent = self.cycle.interest_rate_percent
        if not self.due_date:
            self.due_date = add_months(self.issue_date, self.cycle.loan_term_months)
        super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        if self.member.shg_id != self.shg_id or self.cycle.shg_id != self.shg_id:
            errors["member"] = "Member, cycle and loan must belong to the same group."
        elif self.member.status != Member.Status.ACTIVE:
            errors["member"] = "Loans cannot be issued to an inactive member."
        if not self.pk and not errors and not getattr(self, "skip_limits", False):  # limits apply when the loan is created
            limit = self.member.max_new_loan(self.cycle)
            if self.principal > limit:
                if not self.over_limit_approved_by:
                    errors["principal"] = (
                        f"Above this member's limit of {limit:,} RWF. An administrator must approve it."
                    )
                elif not self.over_limit_approved_by.is_admin:
                    errors["over_limit_approved_by"] = "Only an administrator can approve an over-limit loan."
                elif not self.over_limit_reason:
                    errors["over_limit_reason"] = "Give a reason for approving above the limit."
            if self.principal > self.cycle.lendable_cash():
                errors.setdefault("principal", "The group does not have enough cash to lend this amount.")
        if errors:
            raise ValidationError(errors)

    @property
    def returned(self):
        return self.transactions.filter(type=Transaction.Type.LOAN_RETURN).total()

    @property
    def interest_paid(self):
        return self.transactions.filter(type=Transaction.Type.INTEREST).total()

    @property
    def outstanding(self):
        return max(self.principal - self.returned, 0)

    @property
    def interest_due_on_full_return(self):
        """7% of the principal. Guidance only; the leader records what was actually paid."""
        return int(self.principal * self.interest_rate_percent / 100)

    @classmethod
    def compute_status(cls, *, due_date, outstanding, returned, cancelled_at, today=None):
        today = today or timezone.localdate()
        if cancelled_at:
            return cls.Status.CANCELLED
        if outstanding <= 0:
            return cls.Status.PAID
        if today > due_date:
            return cls.Status.OVERDUE
        return cls.Status.PARTIAL if returned else cls.Status.ACTIVE

    def status(self, today=None):
        returned = self.returned
        return self.compute_status(due_date=self.due_date, outstanding=self.principal - returned,
                                   returned=returned, cancelled_at=self.cancelled_at, today=today)

    @property
    def has_late_fine(self):
        return self.fines.filter(reason=Fine.Reason.LATE_LOAN, cancelled_at__isnull=True).exists()


# ---------------------------------------------------------------------------
# Fines (ibihano) — amount follows each group's own rules
# ---------------------------------------------------------------------------
class FineQuerySet(ScopedQuerySet):
    def with_paid(self):
        paid = (
            Transaction.objects.filter(fine=OuterRef("pk"), type=Transaction.Type.FINE_PAYMENT)
            .order_by().values("fine").annotate(v=signed_sum("amount")).values("v")
        )
        return self.annotate(paid_total=Coalesce(Subquery(paid, output_field=BigIntegerField()), 0,
                                                 output_field=BigIntegerField()))

    def unpaid(self):
        return self.with_paid().filter(cancelled_at__isnull=True, paid_total__lt=F("amount"))


class Fine(TimeStamped):
    class Reason(models.TextChoices):
        LATE_LOAN = "LATE_LOAN", "Late loan"
        MISSED_MEETING = "MISSED_MEETING", "Missed meeting"
        LATE_TO_MEETING = "LATE_TO_MEETING", "Late to meeting"
        OTHER = "OTHER", "Other"

    shg = models.ForeignKey(SHG, on_delete=models.PROTECT, related_name="fines")
    cycle = models.ForeignKey(Cycle, on_delete=models.PROTECT, related_name="fines")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="fines")
    meeting = models.ForeignKey(Meeting, null=True, blank=True, on_delete=models.PROTECT, related_name="fines")
    loan = models.ForeignKey(Loan, null=True, blank=True, on_delete=models.PROTECT, related_name="fines")
    reason = models.CharField(max_length=20, choices=Reason.choices)
    reason_note = models.CharField(max_length=255, blank=True)
    amount = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    issued_date = models.DateField()
    recorded_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)

    objects = FineQuerySet.as_manager()

    class Meta:
        ordering = ["-issued_date"]

    def __str__(self):
        return f"{self.member.full_name} {self.get_reason_display()} {self.amount:,}"

    def clean(self):
        if self.member.shg_id != self.shg_id:
            raise ValidationError("Member belongs to another group.")
        if self.reason == self.Reason.LATE_LOAN:
            if not self.loan or self.loan.member_id != self.member_id:
                raise ValidationError({"loan": "A late-loan fine must be linked to this member's loan."})
        if self.reason == self.Reason.OTHER and not self.reason_note:
            raise ValidationError({"reason_note": "Describe the reason."})
        if self.issued_date and PeriodClosing.is_closed(self.shg_id, self.issued_date):
            raise ValidationError({"issued_date": "That month is closed."})

    @property
    def paid(self):
        return self.payments.total()

    @property
    def is_paid(self):
        return self.paid >= self.amount


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------
class TransactionQuerySet(ScopedQuerySet):
    def total(self, field="amount"):
        return self.aggregate(v=signed_sum(field))["v"]

    def totals_by_type(self):
        rows = self.order_by().values("type").annotate(v=signed_sum("amount"))
        return {r["type"]: r["v"] for r in rows}


class Transaction(models.Model):
    class Type(models.TextChoices):
        SHARE = "SHARE", "Imigabane (shares)"
        INGOBOKA_IN = "INGOBOKA_IN", "Ingoboka (social fund) contribution"
        INGOBOKA_OUT = "INGOBOKA_OUT", "Ingoboka (social fund) payout"
        MUTUELLE = "MUTUELLE", "Mutuelle saving"
        FINE_PAYMENT = "FINE_PAYMENT", "Ibihano (fine) paid"
        LOAN_ISSUE = "LOAN_ISSUE", "Inguzanyo (loan) given"
        LOAN_RETURN = "LOAN_RETURN", "Ayishyuwe (loan returned)"
        INTEREST = "INTEREST", "Inyungu (interest paid)"
        EXPENSE = "EXPENSE", "Group expense"
        OTHER_INCOME = "OTHER_INCOME", "Other money in"
        BANK_DEPOSIT = "BANK_DEPOSIT", "Taken to the bank"

    class ExpenseCategory(models.TextChoices):
        MEETING = "MEETING", "Meeting"
        MATERIALS = "MATERIALS", "Materials"
        TRANSPORT = "TRANSPORT", "Transport"
        ADMIN = "ADMIN", "Administration"
        OTHER = "OTHER", "Other"

    MEMBER_REQUIRED = {"SHARE", "INGOBOKA_IN", "INGOBOKA_OUT", "MUTUELLE",
                       "FINE_PAYMENT", "LOAN_ISSUE", "LOAN_RETURN", "INTEREST"}
    LOAN_REQUIRED = {"LOAN_ISSUE", "LOAN_RETURN", "INTEREST"}
    LOCKED_FIELDS = ("shg_id", "cycle_id", "member_id", "type", "amount", "share_count",
                     "loan_id", "fine_id", "date", "is_reversal", "reverses_id")

    shg = models.ForeignKey(SHG, on_delete=models.PROTECT, related_name="transactions")
    cycle = models.ForeignKey(Cycle, on_delete=models.PROTECT, related_name="transactions")
    meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.PROTECT, related_name="transactions",
        help_text="Blank only for imported history or entries outside a meeting.",
    )
    member = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="transactions")
    date = models.DateField(db_index=True)
    type = models.CharField(max_length=15, choices=Type.choices)
    amount = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    share_count = models.PositiveIntegerField(null=True, blank=True)

    loan = models.ForeignKey(Loan, null=True, blank=True, on_delete=models.PROTECT, related_name="transactions")
    fine = models.ForeignKey(Fine, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    expense_category = models.CharField(max_length=10, choices=ExpenseCategory.choices, blank=True)
    attachment = models.FileField(upload_to="receipts/%Y/%m/", null=True, blank=True)

    description = models.CharField(max_length=255, blank=True)
    carried_by = models.CharField(max_length=120, blank=True, help_text="Who took the money to the bank.")
    reference = models.CharField(max_length=60, blank=True, db_index=True,
                                 help_text="Import source, e.g. 'Amahoro.xlsx!April!K7'")

    is_reversal = models.BooleanField(default=False)
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )

    recorded_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TransactionQuerySet.as_manager()

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["shg", "cycle", "type"]),
            models.Index(fields=["member", "type"]),
        ]

    def __str__(self):
        sign = "-" if self.is_reversal else ""
        return f"{self.date} {self.get_type_display()} {sign}{self.amount:,}"

    def clean(self):
        T = self.Type
        e = {}

        if self.cycle.shg_id != self.shg_id:
            e["cycle"] = "Cycle belongs to another group."
        elif not self.cycle.contains(self.date):
            e["date"] = "Date is outside the group's cycle."
        if self.cycle.status == Cycle.Status.CLOSED:
            e["cycle"] = "This cycle is closed."
        if self.meeting and self.meeting.shg_id != self.shg_id:
            e["meeting"] = "Meeting belongs to another group."
        if PeriodClosing.is_closed(self.shg_id, self.date):
            e["date"] = "That month is closed. Record a correction in the current month."

        if self.type in self.MEMBER_REQUIRED:
            if not self.member:
                e["member"] = "Choose a member."
            elif self.member.shg_id != self.shg_id:
                e["member"] = "Member belongs to another group."

        if self.type == T.SHARE:
            expected = (self.share_count or 0) * self.cycle.share_price
            if not self.share_count:
                e["share_count"] = "Enter the number of shares."
            elif self.amount != expected:
                e["amount"] = f"{self.share_count} shares × {self.cycle.share_price} = {expected:,} RWF."

        if self.type in self.LOAN_REQUIRED:
            if not self.loan:
                e["loan"] = "Choose the loan."
            elif self.loan.member_id != self.member_id:
                e["loan"] = "This loan belongs to another member."
            elif self.loan.cancelled_at and not self.is_reversal:
                e["loan"] = "This loan was cancelled."
            elif self.type == T.LOAN_RETURN and not self.is_reversal and self.amount > self.loan.outstanding:
                e["amount"] = f"Only {self.loan.outstanding:,} RWF is still owed on this loan."

        if self.type == T.FINE_PAYMENT:
            if not self.fine or self.fine.member_id != self.member_id:
                e["fine"] = "Choose this member's fine."
            elif not self.is_reversal:
                if self.fine.cancelled_at:
                    e["fine"] = "This fine was cancelled."
                elif self.amount > self.fine.amount - self.fine.paid:
                    e["amount"] = f"Only {self.fine.amount - self.fine.paid:,} RWF is left to pay on this fine."
        if self.type == T.INGOBOKA_OUT and not self.description:
            e["description"] = "Say who received the social fund payout and why."
        if self.type == T.EXPENSE and not self.expense_category:
            e["expense_category"] = "Choose an expense category."
        if self.type == T.OTHER_INCOME and not self.description:
            e["description"] = "Say where this money came from."
        if self.type == T.BANK_DEPOSIT and not self.carried_by and not self.is_reversal:
            e["carried_by"] = "Write the name of the person taking the money to the bank."

        if self.is_reversal:
            r = self.reverses
            if not r:
                e["reverses"] = "Choose the transaction being corrected."
            elif r.is_reversal or r.type != self.type or r.amount != self.amount:
                e["reverses"] = "A reversal must match the original's type and amount."
            elif Transaction.objects.filter(reverses=r).exclude(pk=self.pk).exists():
                e["reverses"] = "That transaction has already been reversed."

        if e:
            raise ValidationError(e)

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values(*self.LOCKED_FIELDS).first()
            if old and any(old[f] != getattr(self, f) for f in self.LOCKED_FIELDS):
                raise ValidationError("Transactions cannot be edited. Record a reversal instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Transactions cannot be deleted. Record a reversal instead.")

    @db_transaction.atomic
    def reverse(self, user, reason, allow_loan_issue=False):
        """Create the correcting entry, dated today, and log it."""
        self.refresh_from_db()  # never trust unsaved in-memory values
        if self.type == self.Type.LOAN_ISSUE and not allow_loan_issue:
            raise ValidationError("To undo a loan, cancel the loan instead.")
        rev = Transaction(
            shg=self.shg, cycle=self.cycle, member=self.member,
            # Same day as the mistake while that month is open, so the month's totals come out right;
            # today's date once the month is closed.
            date=timezone.localdate() if PeriodClosing.is_closed(self.shg_id, self.date) else self.date,
            type=self.type, amount=self.amount, share_count=self.share_count,
            loan=self.loan, fine=self.fine, expense_category=self.expense_category,
            description=f"Reversal of #{self.pk}: {reason}"[:255], is_reversal=True, reverses=self,
            recorded_by=user,
        )
        rev.full_clean()
        rev.save()
        AuditLog.record(user, AuditLog.Action.REVERSE, self, {"reason": reason, "reversal_id": rev.pk})
        return rev


# ---------------------------------------------------------------------------
# Monthly closing
# ---------------------------------------------------------------------------
class PeriodClosing(models.Model):
    shg = models.ForeignKey(SHG, on_delete=models.PROTECT, related_name="closings")
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    closed_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    closed_at = models.DateTimeField(auto_now_add=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [models.UniqueConstraint(fields=["shg", "year", "month"], name="uniq_period_close")]

    @classmethod
    def is_closed(cls, shg_id, d):
        return cls.objects.filter(shg_id=shg_id, year=d.year, month=d.month).exists()


# ---------------------------------------------------------------------------
# Year-end share-out
# ---------------------------------------------------------------------------
class ShareOut(models.Model):
    """Frozen snapshot of the year-end payout, so it can be printed and audited."""

    cycle = models.OneToOneField(Cycle, on_delete=models.PROTECT, related_name="share_out")
    total_shares = models.PositiveIntegerField()
    interest_collected = models.BigIntegerField()
    fines_collected = models.BigIntegerField()
    expenses = models.BigIntegerField()
    profit_pool = models.BigIntegerField()
    rounding_remainder = models.BigIntegerField(default=0)
    computed_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    computed_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    @db_transaction.atomic
    def compute(cls, cycle, user):
        """payout = shares × share price + (shares ÷ total shares) × profit pool"""
        T = Transaction.Type
        t = cycle.ledger().totals_by_type()
        interest = t.get(T.INTEREST, 0)
        fines = t.get(T.FINE_PAYMENT, 0) if cycle.fines_in_profit else 0
        expenses = t.get(T.EXPENSE, 0)
        pool = interest + fines - expenses

        counts = {m: m.shares(cycle) for m in Member.objects.filter(shg=cycle.shg)}
        total = sum(counts.values())

        so = cls.objects.create(
            cycle=cycle, total_shares=total, interest_collected=interest,
            fines_collected=fines, expenses=expenses, profit_pool=pool, computed_by=user,
        )
        distributed = 0
        for member, n in counts.items():
            if n == 0:
                continue
            profit_share = pool * n // total
            distributed += profit_share
            ShareOutLine.objects.create(
                share_out=so, member=member, shares=n, share_value=n * cycle.share_price,
                profit_share=profit_share, payout=n * cycle.share_price + profit_share,
            )
        so.rounding_remainder = pool - distributed
        so.save(update_fields=["rounding_remainder"])
        return so


class ShareOutLine(models.Model):
    share_out = models.ForeignKey(ShareOut, on_delete=models.CASCADE, related_name="lines")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="share_out_lines")
    shares = models.PositiveIntegerField()
    share_value = models.BigIntegerField()
    profit_share = models.BigIntegerField()
    payout = models.BigIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["share_out", "member"], name="uniq_shareout_member")]


# ---------------------------------------------------------------------------
# Follow-ups and audit
# ---------------------------------------------------------------------------
class FollowUp(TimeStamped):
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    shg = models.ForeignKey(SHG, on_delete=models.PROTECT, related_name="follow_ups")
    member = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="follow_ups")
    loan = models.ForeignKey(Loan, null=True, blank=True, on_delete=models.PROTECT, related_name="follow_ups")
    issue = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    responsible = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="follow_ups")
    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=6, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    resolution = models.TextField(blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    objects = ScopedQuerySet.as_manager()


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Created"
        UPDATE = "UPDATE", "Updated"
        REVERSE = "REVERSE", "Reversed"
        CLOSE_PERIOD = "CLOSE_PERIOD", "Closed month"
        APPROVE = "APPROVE", "Approved"
        IMPORT = "IMPORT", "Imported"

    user = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")
    shg = models.ForeignKey(SHG, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=15, choices=Action.choices)
    model_label = models.CharField(max_length=60)
    object_id = models.CharField(max_length=40)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def record(cls, user, action, obj, changes=None, ip=None):
        return cls.objects.create(
            user=user, action=action, model_label=obj._meta.label, object_id=str(obj.pk),
            shg_id=getattr(obj, "shg_id", None), changes=changes or {}, ip_address=ip,
        )
