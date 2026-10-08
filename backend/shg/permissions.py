"""
Access rules (enforced on the server, never trusted to the React app):

- Admin: read and write everything.
- Leader: read and write only groups with an active LeaderAssignment.
- Viewer: read everything, write nothing.

Querysets are scoped with Model.objects.for_user(user); these classes
decide who may write.
"""
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAdmin(BasePermission):
    message = "Only administrators can do this."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_admin)


class RoleBasedAccess(BasePermission):
    message = "You do not have permission to change this."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        if u.is_admin:
            return True
        if u.role == u.Role.VIEWER:
            return False
        return not getattr(view, "admin_only_write", False)


def can_manage_shg(user, shg_id) -> bool:
    from .models import LeaderAssignment

    if user.is_admin:
        return True
    if user.role != user.Role.LEADER:
        return False
    return LeaderAssignment.objects.filter(leader=user, shg_id=shg_id, end_date__isnull=True).exists()


def require_shg_access(user, shg_id):
    if not can_manage_shg(user, shg_id):
        raise PermissionDenied("You can only manage records for your own group.")
