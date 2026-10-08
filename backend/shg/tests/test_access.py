"""Phase 1: login, roles and the rule that Leader A can never touch SHG002."""
from datetime import date

from rest_framework.test import APITestCase

from accounts.models import User
from shg.models import SHG, AuditLog, Cycle, LeaderAssignment, Member

PW = "Test!Pass-2026"


class AccessTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin", password=PW, role=User.Role.ADMIN)
        cls.leader_a = User.objects.create_user("leader_a", password=PW, role=User.Role.LEADER)
        cls.leader_b = User.objects.create_user("leader_b", password=PW, role=User.Role.LEADER)
        cls.viewer = User.objects.create_user("viewer", password=PW, role=User.Role.VIEWER)

        cls.g1 = SHG.objects.create(code="SHG001", name="Amahoro")
        cls.g2 = SHG.objects.create(code="SHG002", name="Ubumwe")
        LeaderAssignment.objects.create(shg=cls.g1, leader=cls.leader_a)
        LeaderAssignment.objects.create(shg=cls.g2, leader=cls.leader_b)
        for g in (cls.g1, cls.g2):
            Cycle.objects.create(shg=g, name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))

        cls.m1 = Member.objects.create(shg=cls.g1, member_code="SHG001-M001", first_name="Rachel", last_name="Mukangoga")
        cls.m2 = Member.objects.create(shg=cls.g2, member_code="SHG002-M001", first_name="Jean", last_name="Uwera")

    def login(self, user):
        r = self.client.post("/api/auth/login/", {"username": user.username, "password": PW}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        return r.data

    # --- authentication ---------------------------------------------------
    def test_unauthenticated_is_rejected(self):
        self.assertEqual(self.client.get("/api/members/").status_code, 401)

    def test_login_returns_role_and_groups(self):
        data = self.login(self.leader_a)
        self.assertEqual(data["user"]["role"], "LEADER")
        self.assertEqual([g["code"] for g in data["user"]["groups_led"]], ["SHG001"])

    def test_wrong_password(self):
        r = self.client.post("/api/auth/login/", {"username": "leader_a", "password": "nope"}, format="json")
        self.assertEqual(r.status_code, 401)

    # --- leader isolation ---------------------------------------------------
    def test_leader_sees_only_own_members(self):
        self.login(self.leader_a)
        codes = [m["member_code"] for m in self.client.get("/api/members/").data["results"]]
        self.assertEqual(codes, ["SHG001-M001"])

    def test_leader_cannot_open_other_groups_member(self):
        self.login(self.leader_a)
        self.assertEqual(self.client.get(f"/api/members/{self.m2.id}/").status_code, 404)

    def test_leader_cannot_edit_other_groups_member(self):
        self.login(self.leader_a)
        r = self.client.patch(f"/api/members/{self.m2.id}/", {"phone": "0788"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_leader_cannot_create_member_in_other_group(self):
        self.login(self.leader_a)
        r = self.client.post("/api/members/", {"shg": self.g2.id, "first_name": "X", "last_name": "Y"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Member.objects.filter(first_name="X").exists())

    def test_leader_cannot_move_member_to_other_group(self):
        self.login(self.leader_a)
        r = self.client.patch(f"/api/members/{self.m1.id}/", {"shg": self.g2.id}, format="json")
        self.assertEqual(r.status_code, 403)
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.shg_id, self.g1.id)

    def test_leader_sees_only_own_group(self):
        self.login(self.leader_a)
        codes = [g["code"] for g in self.client.get("/api/shgs/").data["results"]]
        self.assertEqual(codes, ["SHG001"])

    def test_leader_cannot_create_group_or_users(self):
        self.login(self.leader_a)
        self.assertEqual(self.client.post("/api/shgs/", {"code": "SHG009", "name": "Z"}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/api/users/").status_code, 403)
        self.assertEqual(self.client.get("/api/audit-logs/").status_code, 403)

    def test_ended_assignment_removes_access(self):
        a = LeaderAssignment.objects.get(leader=self.leader_a)
        a.end_date = date.today()
        a.save()
        self.login(self.leader_a)
        self.assertEqual(self.client.get("/api/members/").data["count"], 0)

    # --- leader writes own group ------------------------------------------------
    def test_leader_registers_member_with_auto_code_and_audit(self):
        self.login(self.leader_a)
        r = self.client.post("/api/members/", {"shg": self.g1.id, "first_name": "Odette", "last_name": "Uwase",
                                               "phone": "0788000000"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["member_code"], "SHG001-M002")
        self.assertTrue(AuditLog.objects.filter(action="CREATE", model_label="shg.Member", user=self.leader_a).exists())

    def test_update_is_audited_with_old_and_new(self):
        self.login(self.leader_a)
        self.client.patch(f"/api/members/{self.m1.id}/", {"phone": "0788111222"}, format="json")
        log = AuditLog.objects.get(action="UPDATE", object_id=str(self.m1.id))
        self.assertEqual(log.changes["phone"], {"old": "", "new": "0788111222"})

    def test_search_member(self):
        self.login(self.admin)
        r = self.client.get("/api/members/?search=mukangoga")
        self.assertEqual([m["id"] for m in r.data["results"]], [self.m1.id])

    def test_delete_not_allowed(self):
        self.login(self.admin)
        self.assertEqual(self.client.delete(f"/api/members/{self.m1.id}/").status_code, 405)

    # --- viewer -------------------------------------------------------------------
    def test_viewer_reads_all_writes_nothing(self):
        self.login(self.viewer)
        self.assertEqual(self.client.get("/api/members/").data["count"], 2)
        r = self.client.patch(f"/api/members/{self.m1.id}/", {"phone": "1"}, format="json")
        self.assertEqual(r.status_code, 403)

    # --- admin -------------------------------------------------------------------------
    def test_admin_creates_group_and_second_active_leader_is_refused(self):
        self.login(self.admin)
        r = self.client.post("/api/shgs/", {"code": "SHG003", "name": "Ituze"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.post("/api/leader-assignments/", {"shg": self.g1.id, "leader": self.leader_b.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_admin_changes_leader(self):
        self.login(self.admin)
        a = LeaderAssignment.objects.get(leader=self.leader_a)
        self.assertEqual(self.client.post(f"/api/leader-assignments/{a.id}/end/").status_code, 200)
        r = self.client.post("/api/leader-assignments/", {"shg": self.g1.id, "leader": self.leader_b.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.login(self.leader_b)
        self.assertEqual(self.client.get("/api/members/").data["count"], 2)

    def test_admin_creates_user_with_hashed_password(self):
        self.login(self.admin)
        r = self.client.post("/api/users/", {"username": "leader_c", "password": "An0ther!Pass", "role": "LEADER"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertNotIn("password", r.data)
        self.assertTrue(User.objects.get(username="leader_c").check_password("An0ther!Pass"))
