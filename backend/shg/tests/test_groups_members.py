"""Step 4b: creating groups from the screen and registering many members at once."""
from datetime import date

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User
from shg.models import SHG, Cycle, LeaderAssignment, Member

PW = "Test!Pass-2026"


class GroupAndBulkMemberTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin", password=PW, role=User.Role.ADMIN)
        cls.lead = User.objects.create_user("lead", password=PW, role=User.Role.LEADER)
        cls.amahoro = SHG.objects.create(code="SHG001", name="Amahoro")
        cls.other = SHG.objects.create(code="SHG002", name="Ubumwe")
        LeaderAssignment.objects.create(shg=cls.amahoro, leader=cls.lead)

    def login(self, user):
        r = self.client.post("/api/auth/login/", {"username": user.username, "password": PW}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    def test_admin_creates_group_with_auto_code_and_cycle(self):
        self.login(self.admin)
        r = self.client.post("/api/shgs/", {"name": "Itetero"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["code"], "SHG003")
        g = SHG.objects.get(pk=r.data["id"])
        cycle = Cycle.objects.get(shg=g)
        self.assertEqual(cycle.name, str(timezone.localdate().year))
        self.assertEqual(cycle.share_price, 500)

    def test_duplicate_group_name_refused(self):
        self.login(self.admin)
        self.assertEqual(self.client.post("/api/shgs/", {"name": "amahoro"}, format="json").status_code, 400)

    def test_leader_cannot_create_group(self):
        self.login(self.lead)
        self.assertEqual(self.client.post("/api/shgs/", {"name": "Abadahigwa"}, format="json").status_code, 403)

    def test_groups_listed_by_name(self):
        self.login(self.admin)
        names = [g["name"] for g in self.client.get("/api/shgs/").data["results"]]
        self.assertEqual(names, ["Amahoro", "Ubumwe"])

    def test_bulk_add_members_numbered_in_order(self):
        Member.objects.create(shg=self.amahoro, member_code="SHG001-M007", first_name="A", last_name="B")
        self.login(self.lead)
        r = self.client.post("/api/members/bulk/", {"shg": self.amahoro.id, "members": [
            {"first_name": "Christine", "last_name": "KABEHO", "phone": "0788000001"},
            {"first_name": "Laurence", "last_name": "NYIRANDAGIJIMANA"},
            {"first_name": "Odette", "last_name": "UWASE"},
        ]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual([m["member_code"] for m in r.data], ["SHG001-M008", "SHG001-M009", "SHG001-M010"])
        self.assertEqual(Member.objects.filter(shg=self.amahoro).count(), 4)

    def test_bulk_add_is_all_or_nothing(self):
        self.login(self.lead)
        r = self.client.post("/api/members/bulk/", {"shg": self.amahoro.id, "members": [
            {"first_name": "Ok", "last_name": "One"},
            {"first_name": "", "last_name": "Two"},
        ]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Member.objects.count(), 0)

    def test_leader_cannot_bulk_add_to_other_group(self):
        self.login(self.lead)
        r = self.client.post("/api/members/bulk/", {"shg": self.other.id, "members": [
            {"first_name": "X", "last_name": "Y"}]}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Member.objects.count(), 0)
