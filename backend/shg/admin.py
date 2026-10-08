from django.contrib import admin

from .models import (SHG, Attendance, AuditLog, Cycle, Fine, FollowUp, LeaderAssignment, Loan, Meeting,
                     Member, PeriodClosing, ShareOut, ShareOutLine, Transaction)


class LeaderInline(admin.TabularInline):
    model = LeaderAssignment
    fk_name = "shg"
    extra = 0
    fields = ("leader", "start_date", "end_date")


@admin.register(SHG)
class SHGAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "location", "status", "current_leader")
    list_filter = ("status",)
    search_fields = ("code", "name", "location")
    inlines = [LeaderInline]


@admin.register(Cycle)
class CycleAdmin(admin.ModelAdmin):
    list_display = ("shg", "name", "start_date", "end_date", "share_price", "interest_rate_percent",
                    "loan_multiplier", "status")
    list_filter = ("status", "shg")


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("member_code", "full_name", "shg", "phone", "status", "date_joined")
    list_filter = ("shg", "status", "gender")
    search_fields = ("member_code", "first_name", "last_name", "phone", "national_id")


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("shg", "date", "recorded_by")
    list_filter = ("shg",)
    date_hierarchy = "date"


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("id", "member", "shg", "principal", "issue_date", "due_date")
    list_filter = ("shg",)
    search_fields = ("member__first_name", "member__last_name", "member__member_code")


@admin.register(Fine)
class FineAdmin(admin.ModelAdmin):
    list_display = ("member", "shg", "reason", "amount", "issued_date")
    list_filter = ("shg", "reason")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Read-only: money is corrected by reversal entries through the API, never edited here."""

    list_display = ("id", "date", "shg", "member", "type", "amount", "is_reversal", "recorded_by")
    list_filter = ("shg", "type", "is_reversal")
    search_fields = ("member__first_name", "member__last_name", "reference")
    date_hierarchy = "date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "model_label", "object_id", "shg")
    list_filter = ("action", "model_label", "shg")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([PeriodClosing, ShareOut, ShareOutLine, FollowUp, Attendance, LeaderAssignment])
