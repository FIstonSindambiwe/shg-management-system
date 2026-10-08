"""Model-level money rules (verified before the API for money is built)."""
from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from shg.models import SHG, Cycle, Fine, LeaderAssignment, Loan, Meeting, Member, PeriodClosing, ShareOut, Transaction

T = Transaction.Type


class LedgerRuleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", password="x", role="ADMIN")
        self.lead = User.objects.create_user("lead", password="x", role="LEADER")
        self.g = SHG.objects.create(code="SHG001", name="Amahoro")
        self.g2 = SHG.objects.create(code="SHG002", name="Ubumwe")
        LeaderAssignment.objects.create(shg=self.g, leader=self.lead)
        self.c = Cycle.objects.create(shg=self.g, name="2026", start_date=date(2026, 1, 1),
                                      end_date=date(2026, 12, 31), loan_multiplier=3)
        self.rachel = Member.objects.create(shg=self.g, member_code="SHG001-M001", first_name="Rachel", last_name="M")
        self.jean = Member.objects.create(shg=self.g, member_code="SHG001-M002", first_name="Jean", last_name="U")
        self.other = Member.objects.create(shg=self.g2, member_code="SHG002-M001", first_name="X", last_name="O")
        self.meeting = Meeting.objects.create(shg=self.g, cycle=self.c, date=date(2026, 4, 1), recorded_by=self.lead)
        self.tx(member=self.rachel, type=T.SHARE, share_count=100, amount=50000)
        self.tx(member=self.jean, type=T.SHARE, share_count=50, amount=25000)

    def tx(self, **kw):
        kw.setdefault("shg", self.g); kw.setdefault("cycle", self.c)
        kw.setdefault("recorded_by", self.lead); kw.setdefault("date", date(2026, 4, 1))
        t = Transaction(**kw); t.full_clean(); t.save(); return t

    def make_loan(self, principal=60000):
        loan = Loan(shg=self.g, cycle=self.c, member=self.rachel, principal=principal,
                    issue_date=date(2026, 4, 1), recorded_by=self.lead)
        loan.full_clean(); loan.save()
        self.tx(member=self.rachel, type=T.LOAN_ISSUE, amount=principal, loan=loan)
        return loan

    def test_share_amount_must_match_count(self):
        with self.assertRaises(ValidationError):
            self.tx(member=self.rachel, type=T.SHARE, share_count=5, amount=2000)

    def test_loan_blocked_above_group_cash(self):
        loan = Loan(shg=self.g, cycle=self.c, member=self.rachel, principal=100000,
                    issue_date=date(2026, 4, 1), recorded_by=self.lead)
        with self.assertRaises(ValidationError):
            loan.full_clean()

    def test_loan_limit_by_shares(self):
        self.c.loan_multiplier = 1; self.c.save()
        loan = Loan(shg=self.g, cycle=self.c, member=self.jean, principal=30000,
                    issue_date=date(2026, 4, 1), recorded_by=self.lead)
        with self.assertRaises(ValidationError):
            loan.full_clean()

    def test_due_date_status_and_late_fine_report(self):
        loan = self.make_loan()
        self.assertEqual(loan.due_date, date(2026, 7, 1))
        self.tx(member=self.rachel, type=T.INTEREST, amount=4200, loan=loan, date=date(2026, 5, 6))
        self.tx(member=self.rachel, type=T.LOAN_RETURN, amount=30000, loan=loan, date=date(2026, 6, 3))
        self.assertEqual(loan.outstanding, 30000)
        self.assertEqual(loan.status(date(2026, 6, 10)), Loan.Status.PARTIAL)
        self.assertEqual(loan.status(date(2026, 7, 5)), Loan.Status.OVERDUE)
        self.assertEqual(Loan.objects.overdue_without_late_fine(date(2026, 7, 5)).count(), 1)
        Fine.objects.create(shg=self.g, cycle=self.c, member=self.rachel, loan=loan, reason=Fine.Reason.LATE_LOAN,
                            amount=1000, issued_date=date(2026, 7, 8), recorded_by=self.lead)
        self.assertEqual(Loan.objects.overdue_without_late_fine(date(2026, 7, 5)).count(), 0)

    def test_cannot_return_more_than_owed(self):
        loan = self.make_loan()
        with self.assertRaises(ValidationError):
            self.tx(member=self.rachel, type=T.LOAN_RETURN, amount=70000, loan=loan)

    def test_transactions_are_immutable_and_reversal_corrects(self):
        loan = self.make_loan()
        r = self.tx(member=self.rachel, type=T.LOAN_RETURN, amount=30000, loan=loan, date=date(2026, 6, 3))
        r.amount = 1
        with self.assertRaises(ValidationError):
            r.save()
        with self.assertRaises(ValidationError):
            r.delete()
        r.reverse(self.admin, "wrong week")
        self.assertEqual(loan.outstanding, 60000)
        # the database-side balance must agree (this path broke on MySQL before the Cast fix)
        self.assertEqual(Loan.objects.open().get(pk=loan.pk).outstanding_total, 60000)
        with self.assertRaises(ValidationError):
            r.reverse(self.admin, "again")

    def test_closed_month_rejects_entries(self):
        PeriodClosing.objects.create(shg=self.g, year=2026, month=4, closed_by=self.admin)
        with self.assertRaises(ValidationError):
            self.tx(member=self.jean, type=T.INGOBOKA_IN, amount=100, date=date(2026, 4, 15))

    def test_member_from_other_group_rejected(self):
        with self.assertRaises(ValidationError):
            self.tx(member=self.other, type=T.INGOBOKA_IN, amount=100)

    def test_share_out_split_by_shares(self):
        loan = self.make_loan()
        self.tx(member=self.rachel, type=T.INTEREST, amount=4200, loan=loan)
        fine = Fine.objects.create(shg=self.g, cycle=self.c, member=self.rachel, reason=Fine.Reason.MISSED_MEETING,
                                   amount=1000, issued_date=date(2026, 4, 1), recorded_by=self.lead)
        self.tx(member=self.rachel, type=T.FINE_PAYMENT, amount=1000, fine=fine)
        so = ShareOut.compute(self.c, self.admin)
        lines = {l.member_id: l for l in so.lines.all()}
        self.assertEqual(so.profit_pool, 5200)
        self.assertEqual(lines[self.rachel.id].profit_share, 3466)
        self.assertEqual(lines[self.jean.id].profit_share, 1733)
        self.assertEqual(lines[self.rachel.id].payout, 53466)
        self.assertEqual(so.rounding_remainder, 1)
