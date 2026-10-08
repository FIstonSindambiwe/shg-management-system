"""
accounts/models.py

Custom user with a role. Must exist BEFORE the first `migrate`,
and settings.py needs:  AUTH_USER_MODEL = "accounts.User"
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        LEADER = "LEADER", "Group leader"
        VIEWER = "VIEWER", "Supervisor / viewer"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.LEADER)
    phone = models.CharField(max_length=20, blank=True)

    @property
    def is_admin(self) -> bool:
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def can_see_all_groups(self) -> bool:
        return self.is_admin or self.role == self.Role.VIEWER

    def active_shg_ids(self):
        """IDs of the groups this leader currently manages."""
        return self.leader_assignments.filter(end_date__isnull=True).values_list(
            "shg_id", flat=True
        )

    def __str__(self):
        return self.get_full_name() or self.username
