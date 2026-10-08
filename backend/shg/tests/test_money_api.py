"""Step 2: the weekly sheet, loans, fines, corrections and month closing through the API."""
import uuid
from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User
from shg.models import SHG, AuditLog, Cycle, Fine, LeaderAssignment, Loan, Meeting, Member, Transaction

PW = "Test!Pass-2026"
T = Transaction.Type


class MoneyApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin", password=PW, role=User.Role.ADMIN)
        cls.lead_a = User.objects.create_user("lead_a", password=PW, role=User.Role.LEADER)
        cls.lead_b = User.objects.create_user("lead_b", password=PW, role=User.Role.LEADER)
        cls.viewer = User.objects.create_user("viewer", password=PW, role=User.Role.VIEWER)

        cls.g1 = SHG.objects.create(code="SHG001", name="Amahoro")
        cls.g2 = SHG.objects.create(code="SHG002", name="Ubumwe")
        LeaderAssignment.objects.create(shg=cls.g1, leader=cls.lead_a)
        LeaderAssignment.objects.create(shg=cls.g2, leader=cls.lead_b)
        year = timezone.localdate().year
        cls.c1 = Cycle.objects.create(shg=cls.g1, name=str(year), start_date=date(year, 1, 1),
                                      end_date=date(year, 12, 31), loan_multiplier=3)
        cls.c2 = Cycle.objects.create(shg=cls.g2, name=str(year), start_date=date(year, 1, 1),
                                      end_date=date(year, 12, 31))
        cls.rachel = Member.objects.create(shg=cls.g1, member_code="SHG001-M001", first_name="Rachel", last_name="Mukangoga")
        cls.jean = Member.objects.create(shg=cls.g1, member_code="SHG001-M002", first_name="Jean", last_name="Uwera")
        cls.left = Member.objects.create(shg=cls.g1, member_code="SHG001-M003", first_name="Old", last_name="Left",
                                         status=Member.Status.LEFT)
        cls.other = Member.objects.create(shg=cls.g2, member_code="SHG002-M001", first_name="X", last_name="Other")

    # ---- helpers ---------------------------------------------------------------
    def login(self, user):
        r = self.client.post("/api/auth/login/", {"username": user.username, "password": PW}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    def meeting(self, d=None, shg=None):
        self.login(self.lead_a)
        d = d or timezone.localdate().replace(day=1)
        r = self.client.post("/api/meetings/", {"shg": (shg or self.g1).id, "date": str(d)}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["id"]

    def post_sheet(self, meeting_id, rows, submission_id=None):
        return self.client.post(f"/api/meetings/{meeting_id}/sheet/",
                                {"submission_id": str(submission_id or uuid.uuid4()), "rows": rows}, format="json")

    def fund_group(self, meeting_id):
        """Rachel buys 100 shares (50,000), Jean 50 (25,000): the group can lend 75,000."""
        r = self.post_sheet(meeting_id, [
            {"member": self.rachel.id, "shares": 100, "ingoboka": 100, "mutuelle": 500, "present": True},
            {"member": self.jean.id, "shares": 50, "ingoboka": 100, "mutuelle": 500, "present": True},
        ])
        self.assertEqual(r.status_code, 201, r.data)
        return r

    # ---- meetings -------------------------------------------------------------------
    def test_meeting_gets_cycle_automatically(self):
        mid = self.meeting()
        self.assertEqual(Meeting.objects.get(pk=mid).cycle_id, self.c1.id)

    def test_meeting_outside_cycle_refused(self):
        self.login(self.lead_a)
        r = self.client.post("/api/meetings/", {"shg": self.g1.id, "date": "2030-01-01"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_leader_cannot_create_meeting_for_other_group(self):
        self.login(self.lead_a)
        r = self.client.post("/api/meetings/", {"shg": self.g2.id, "date": str(timezone.localdate())}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_two_meetings_same_day_refused(self):
        d = timezone.localdate().replace(day=2)
        self.meeting(d)
        r = self.client.post("/api/meetings/", {"shg": self.g1.id, "date": str(d)}, format="json")
        self.assertEqual(r.status_code, 400)

    # ---- sheet ------------------------------------------------------------------------
    def test_sheet_lists_active_members_only(self):
        mid = self.meeting()
        rows = self.client.get(f"/api/meetings/{mid}/sheet/").data["rows"]
        self.assertEqual([r["member"]["member_code"] for r in rows], ["SHG001-M001", "SHG001-M002"])
        self.assertEqual(self.client.get(f"/api/meetings/{mid}/sheet/").data["cycle"]["share_price"], 500)

    def test_sheet_saves_and_totals(self):
        mid = self.meeting()
        r = self.fund_group(mid)
        self.assertEqual(r.data["saved"]["transactions"], 6)
        rachel = next(x for x in r.data["rows"] if x["member"]["id"] == self.rachel.id)
        self.assertEqual(rachel["recorded"]["shares"], 100)
        self.assertEqual(rachel["recorded"]["share_value"], 50000)
        self.assertEqual(rachel["present"], True)
        self.assertEqual(r.data["meeting_totals"]["SHARE"], 75000)
        self.assertEqual(r.data["meeting_totals"]["INGOBOKA_IN"], 200)
        self.assertEqual(r.data["meeting_totals"]["MUTUELLE"], 1000)

    def test_share_amount_is_calculated_by_server(self):
        mid = self.meeting()
        self.post_sheet(mid, [{"member": self.jean.id, "shares": 5}])
        self.assertEqual(Transaction.objects.get(member=self.jean, type=T.SHARE).amount, 2500)

    def test_double_tap_does_not_record_twice(self):
        mid = self.meeting()
        sid = uuid.uuid4()
        rows = [{"member": self.jean.id, "shares": 5, "ingoboka": 100}]
        self.assertEqual(self.post_sheet(mid, rows, sid).status_code, 201)
        r2 = self.post_sheet(mid, rows, sid)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.data["saved"]["duplicate"])
        self.assertEqual(Transaction.objects.filter(member=self.jean).count(), 2)

    def test_one_bad_row_saves_nothing(self):
        mid = self.meeting()
        r = self.post_sheet(mid, [
            {"member": self.rachel.id, "shares": 10},
            {"member": self.other.id, "ingoboka": 100},
        ])
        self.assertEqual(r.status_code, 400)
        self.assertIn("1", r.data["rows"])
        self.assertEqual(Transaction.objects.count(), 0)

    def test_same_member_twice_refused(self):
        mid = self.meeting()
        r = self.post_sheet(mid, [{"member": self.jean.id, "shares": 1}, {"member": self.jean.id, "shares": 1}])
        self.assertEqual(r.status_code, 400)

    def test_leader_b_cannot_see_or_save_leader_a_sheet(self):
        mid = self.meeting()
        self.login(self.lead_b)
        self.assertEqual(self.client.get(f"/api/meetings/{mid}/sheet/").status_code, 404)
        self.assertEqual(self.post_sheet(mid, [{"member": self.jean.id, "shares": 1}]).status_code, 404)

    def test_viewer_reads_sheet_but_cannot_save(self):
        mid = self.meeting()
        self.login(self.viewer)
        self.assertEqual(self.client.get(f"/api/meetings/{mid}/sheet/").status_code, 200)
        self.assertEqual(self.post_sheet(mid, [{"member": self.jean.id, "shares": 1}]).status_code, 403)

    def test_new_fine_paid_on_the_spot(self):
        mid = self.meeting()
        r = self.post_sheet(mid, [{"member": self.jean.id, "new_fines": [
            {"reason": "LATE_TO_MEETING", "amount": 100, "paid_now": True}]}])
        self.assertEqual(r.status_code, 201, r.data)
        fine = Fine.objects.get(member=self.jean)
        self.assertTrue(fine.is_paid)

    def test_audit_records_sheet_save(self):
        mid = self.meeting()
        self.fund_group(mid)
        self.assertTrue(AuditLog.objects.filter(model_label="shg.Meeting", action="CREATE",
                                                changes__transactions=6).exists())

    # ---- loans -----------------------------------------------------------------------------
    def test_loan_flow_issue_interest_return(self):
        mid = self.meeting()
        self.fund_group(mid)
        r = self.client.post("/api/loans/", {"member": self.rachel.id, "principal": 60000, "meeting": mid}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        loan_id = r.data["id"]
        self.assertEqual(r.data["outstanding"], 60000)
        self.assertEqual(r.data["interest_due_on_full_return"], 4200)
        self.assertEqual(Transaction.objects.get(loan_id=loan_id, type=T.LOAN_ISSUE).amount, 60000)

        sheet = self.client.get(f"/api/meetings/{mid}/sheet/").data
        rachel = next(x for x in sheet["rows"] if x["member"]["id"] == self.rachel.id)
        self.assertEqual(rachel["open_loans"][0]["id"], loan_id)

        r = self.post_sheet(mid, [{"member": self.rachel.id, "loan_payments": [
            {"loan": loan_id, "interest": 4200, "returned": 30000}]}])
        self.assertEqual(r.status_code, 201, r.data)
        loan = self.client.get(f"/api/loans/{loan_id}/").data
        self.assertEqual((loan["returned"], loan["interest_paid"], loan["outstanding"], loan["status"]),
                         (30000, 4200, 30000, "PARTIAL"))

    def test_cannot_return_more_than_owed(self):
        mid = self.meeting()
        self.fund_group(mid)
        loan_id = self.client.post("/api/loans/", {"member": self.rachel.id, "principal": 10000}, format="json").data["id"]
        r = self.post_sheet(mid, [{"member": self.rachel.id, "loan_payments": [{"loan": loan_id, "returned": 20000}]}])
        self.assertEqual(r.status_code, 400)

    def test_cannot_pay_another_members_loan(self):
        mid = self.meeting()
        self.fund_group(mid)
        loan_id = self.client.post("/api/loans/", {"member": self.rachel.id, "principal": 10000}, format="json").data["id"]
        r = self.post_sheet(mid, [{"member": self.jean.id, "loan_payments": [{"loan": loan_id, "returned": 1000}]}])
        self.assertEqual(r.status_code, 400)

    def test_loan_over_limit_leader_refused_admin_can_approve(self):
        mid = self.meeting()
        self.fund_group(mid)
        self.c1.loan_multiplier = 1
        self.c1.save()
        r = self.client.post("/api/loans/", {"member": self.jean.id, "principal": 30000}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("principal", r.data)
        r = self.client.post("/api/loans/", {"member": self.jean.id, "principal": 30000,
                                             "over_limit_reason": "x"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.login(self.admin)
        r = self.client.post("/api/loans/", {"member": self.jean.id, "principal": 30000,
                                             "over_limit_reason": "Committee approved, guarantor Rachel"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_loan_above_group_cash_refused(self):
        mid = self.meeting()
        self.fund_group(mid)
        r = self.client.post("/api/loans/", {"member": self.rachel.id, "principal": 90000}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_overdue_and_missing_late_fine_filters(self):
        mid = self.meeting()
        self.fund_group(mid)
        old = timezone.localdate() - timedelta(days=120)
        cycle_start = self.c1.start_date
        issue = max(old, cycle_start)
        loan_id = self.client.post("/api/loans/", {"member": self.rachel.id, "principal": 10000,
                                                   "issue_date": str(issue)}, format="json").data["id"]
        loan = Loan.objects.get(pk=loan_id)
        if loan.due_date >= timezone.localdate():
            Loan.objects.filter(pk=loan_id).update(due_date=timezone.localdate() - timedelta(days=1))
        ids = [x["id"] for x in self.client.get("/api/loans/?status=overdue").data["results"]]
        self.assertEqual(ids, [loan_id])
        missing = [x["id"] for x in self.client.get("/api/loans/?late_fine_missing=true").data["results"]]
        self.assertEqual(missing, [loan_id])

        r = self.client.post("/api/fines/", {"member": self.rachel.id, "reason": "LATE_LOAN", "loan": loan_id,
                                             "amount": 1000}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.client.get("/api/loans/?late_fine_missing=true").data["count"], 0)
        self.assertEqual(self.client.get("/api/fines/?unpaid=true").data["count"], 1)

    def test_admin_cancels_unpaid_loan(self):
        mid = self.meeting()
        self.fund_group(mid)
        loan_id = self.client.post("/api/loans/", {"member": self.rachel.id, "principal": 10000}, format="json").data["id"]
        self.assertEqual(self.client.post(f"/api/loans/{loan_id}/cancel/", {"reason": "typo"}, format="json").status_code, 403)
        self.login(self.admin)
        r = self.client.post(f"/api/loans/{loan_id}/cancel/", {"reason": "wrong member"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "CANCELLED")
        self.assertEqual(self.c1.lendable_cash(), 75000)

    # ---- corrections, closing ------------------------------------------------------------------------
    def test_reverse_wrong_entry(self):
        mid = self.meeting()
        self.fund_group(mid)
        tx = Transaction.objects.get(member=self.jean, type=T.SHARE)
        r = self.client.post(f"/api/transactions/{tx.id}/reverse/", {"reason": "Jean bought 5 not 50"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        summary = self.client.get(f"/api/members/{self.jean.id}/summary/").data
        self.assertEqual(summary["shares"], 0)
        self.assertEqual(self.client.post(f"/api/transactions/{tx.id}/reverse/", {"reason": "again"},
                                          format="json").status_code, 400)

    def test_loan_issue_cannot_be_reversed_directly(self):
        mid = self.meeting()
        self.fund_group(mid)
        loan_id = self.client.post("/api/loans/", {"member": self.rachel.id, "principal": 10000}, format="json").data["id"]
        tx = Transaction.objects.get(loan_id=loan_id, type=T.LOAN_ISSUE)
        self.assertEqual(self.client.post(f"/api/transactions/{tx.id}/reverse/", {"reason": "x"},
                                          format="json").status_code, 400)

    def test_leader_b_cannot_reverse_group_a_entry(self):
        mid = self.meeting()
        self.fund_group(mid)
        tx = Transaction.objects.filter(shg=self.g1).first()
        self.login(self.lead_b)
        self.assertEqual(self.client.post(f"/api/transactions/{tx.id}/reverse/", {"reason": "x"},
                                          format="json").status_code, 404)

    def test_closed_month_blocks_sheet_and_new_meetings(self):
        d = timezone.localdate().replace(day=1)
        mid = self.meeting(d)
        self.login(self.lead_a)
        self.assertEqual(self.client.post("/api/period-closings/", {"shg": self.g1.id, "year": d.year,
                                                                    "month": d.month}, format="json").status_code, 403)
        self.login(self.admin)
        r = self.client.post("/api/period-closings/", {"shg": self.g1.id, "year": d.year, "month": d.month}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.login(self.lead_a)
        self.assertEqual(self.post_sheet(mid, [{"member": self.jean.id, "shares": 1}]).status_code, 400)
        r = self.client.post("/api/meetings/", {"shg": self.g1.id, "date": str(d.replace(day=3))}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_expense_and_social_fund_payout(self):
        mid = self.meeting()
        self.fund_group(mid)
        r = self.client.post("/api/transactions/", {"shg": self.g1.id, "type": "EXPENSE", "amount": 2000,
                                                    "expense_category": "MATERIALS", "description": "Notebook"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.post("/api/transactions/", {"shg": self.g1.id, "type": "INGOBOKA_OUT", "amount": 150,
                                                    "member": self.jean.id}, format="json")
        self.assertEqual(r.status_code, 400)  # description required
        r = self.client.post("/api/transactions/", {"shg": self.g1.id, "type": "SHARE", "amount": 500}, format="json")
        self.assertEqual(r.status_code, 400)  # shares only through the weekly sheet

    def test_member_summary(self):
        mid = self.meeting()
        self.fund_group(mid)
        s = self.client.get(f"/api/members/{self.rachel.id}/summary/").data
        self.assertEqual((s["shares"], s["share_value"], s["ingoboka"], s["mutuelle"]), (100, 50000, 100, 500))
        self.assertEqual(s["loan_limit"]["max_new_loan"], 150000)
        self.assertEqual(s["loan_limit"]["group_lendable_cash"], 75000)
