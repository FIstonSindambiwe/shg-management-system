"""
Create a starting admin, the Amahoro group, its 2026 cycle and one leader.

    python manage.py seed_demo --admin-password "Str0ng!Pass" --leader-password "Leader!Pass1"

Safe to run more than once: existing records are left as they are.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from shg.models import SHG, Cycle, LeaderAssignment


class Command(BaseCommand):
    help = "Seed an admin user, SHG001 Amahoro, its 2026 cycle and a leader account."

    def add_arguments(self, parser):
        parser.add_argument("--admin-password")
        parser.add_argument("--leader-password")
        parser.add_argument("--check", action="store_true",
                            help="Exit with code 0 if the admin user exists, 1 if not. Changes nothing.")

    def handle(self, *args, **opts):
        if opts["check"]:
            raise SystemExit(0 if User.objects.filter(username="admin").exists() else 1)
        if not opts["admin_password"] or not opts["leader_password"]:
            raise CommandError("Give both --admin-password and --leader-password.")
        self.seed(opts)

    @transaction.atomic
    def seed(self, opts):
        admin, created = User.objects.get_or_create(
            username="admin", defaults={"role": User.Role.ADMIN, "is_staff": True, "is_superuser": True}
        )
        if created:
            admin.set_password(opts["admin_password"])
            admin.save()
        self.stdout.write(f"admin user: {'created' if created else 'already exists'}")

        shg, created = SHG.objects.get_or_create(
            code="SHG001", defaults={"name": "Amahoro", "location": "", "status": SHG.Status.ACTIVE}
        )
        self.stdout.write(f"{shg}: {'created' if created else 'already exists'}")

        cycle, created = Cycle.objects.get_or_create(
            shg=shg, name="2026", defaults={"start_date": date(2026, 1, 1), "end_date": date(2026, 12, 31)}
        )
        self.stdout.write(f"cycle {cycle}: {'created' if created else 'already exists'}")

        leader, created = User.objects.get_or_create(
            username="leader_amahoro", defaults={"role": User.Role.LEADER, "first_name": "Amahoro", "last_name": "Leader"}
        )
        if created:
            leader.set_password(opts["leader_password"])
            leader.save()
        if not LeaderAssignment.objects.filter(shg=shg, end_date__isnull=True).exists():
            LeaderAssignment.objects.create(shg=shg, leader=leader, assigned_by=admin)
        self.stdout.write(self.style.SUCCESS("Seed complete."))
