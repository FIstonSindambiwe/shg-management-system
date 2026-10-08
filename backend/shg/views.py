import datetime
from decimal import Decimal

from django.db.models import Count, F, Q
from django.forms.models import model_to_dict
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status as http

from . import services
from .models import SHG, AuditLog, Cycle, Fine, LeaderAssignment, Loan, Meeting, Member, PeriodClosing, Transaction
from .permissions import IsAdmin, RoleBasedAccess, require_shg_access
from django.db import transaction as db_transaction

from .serializers import (AuditLogSerializer, BulkMembersInput, CycleSerializer, DirectTransactionSerializer, FineSerializer,
                          LeaderAssignmentSerializer, LoanCreateSerializer, LoanSerializer, MeetingSerializer,
                          MemberSerializer, PeriodClosingSerializer, ReasonSerializer, SHGSerializer, SheetInput,
                          TransactionSerializer)


def as_drf(exc: DjangoValidationError):
    """Django model errors -> DRF 400 response body."""
    return ValidationError(getattr(exc, "message_dict", None) or {"non_field_errors": exc.messages})


def snapshot(obj):
    def plain(v):
        if isinstance(v, (datetime.date, datetime.datetime, Decimal)):
            return str(v)
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        return str(v)
    return {k: plain(v) for k, v in model_to_dict(obj).items()}


def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")


class ScopedModelViewSet(viewsets.ModelViewSet):
    """
    Base for every group-owned resource:
    - queryset always passes through Model.objects.for_user()
    - writes are checked against the group the record belongs to
    - every create/update is written to the audit log
    - no DELETE: archive or change status instead
    """

    model = None
    admin_only_write = False
    permission_classes = [permissions.IsAuthenticated, RoleBasedAccess]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return self.model.objects.for_user(self.request.user)

    def shg_id_for(self, validated_data, instance=None):
        shg = validated_data.get("shg") or getattr(instance, "shg", None)
        return shg.id if shg else None

    def extra_save_fields(self):
        return {}

    def perform_create(self, serializer):
        shg_id = self.shg_id_for(serializer.validated_data)
        if shg_id and not self.admin_only_write:
            require_shg_access(self.request.user, shg_id)
        instance = serializer.save(**self.extra_save_fields())
        AuditLog.record(self.request.user, AuditLog.Action.CREATE, instance, snapshot(instance), client_ip(self.request))

    def perform_update(self, serializer):
        instance = serializer.instance
        before = snapshot(instance)
        if getattr(instance, "shg_id", None) and not self.admin_only_write:
            require_shg_access(self.request.user, instance.shg_id)
            new_shg = serializer.validated_data.get("shg")
            if new_shg and new_shg.id != instance.shg_id and not self.request.user.is_admin:
                raise PermissionDenied("Only an administrator can move a record to another group.")
        instance = serializer.save()
        after = snapshot(instance)
        changes = {k: {"old": before.get(k), "new": v} for k, v in after.items() if before.get(k) != v}
        if changes:
            AuditLog.record(self.request.user, AuditLog.Action.UPDATE, instance, changes, client_ip(self.request))


class SHGViewSet(ScopedModelViewSet):
    model = SHG
    serializer_class = SHGSerializer
    admin_only_write = True
    filterset_fields = ["status"]
    search_fields = ["code", "name", "location"]
    ordering_fields = ["code", "name", "formation_date"]

    def get_queryset(self):
        return super().get_queryset().annotate(
            member_count=Count("members", filter=Q(members__status=Member.Status.ACTIVE), distinct=True)
        ).order_by("name")

    def perform_create(self, serializer):
        """A new group gets this year's savings cycle straight away, so meetings can start."""
        super().perform_create(serializer)
        shg = serializer.instance
        year = timezone.localdate().year
        if not shg.cycles.exists():
            Cycle.objects.create(shg=shg, name=str(year), start_date=datetime.date(year, 1, 1),
                                 end_date=datetime.date(year, 12, 31))


class CycleViewSet(ScopedModelViewSet):
    model = Cycle
    serializer_class = CycleSerializer
    admin_only_write = True
    filterset_fields = ["shg", "status"]


class LeaderAssignmentViewSet(ScopedModelViewSet):
    model = LeaderAssignment
    serializer_class = LeaderAssignmentSerializer
    admin_only_write = True
    filterset_fields = ["shg", "leader"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("shg", "leader")
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(end_date__isnull=True)
        return qs

    def extra_save_fields(self):
        return {"assigned_by": self.request.user}

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated, IsAdmin])
    def end(self, request, pk=None):
        """End a leader's assignment today (before assigning a new leader)."""
        a = self.get_object()
        if a.end_date:
            raise ValidationError({"end_date": "This assignment has already ended."})
        a.end_date = timezone.localdate()
        a.save(update_fields=["end_date"])
        AuditLog.record(request.user, AuditLog.Action.UPDATE, a, {"end_date": {"old": None, "new": str(a.end_date)}},
                        client_ip(request))
        return Response(LeaderAssignmentSerializer(a).data)


class MemberViewSet(ScopedModelViewSet):
    model = Member
    serializer_class = MemberSerializer
    filterset_fields = ["shg", "status", "gender"]
    search_fields = ["member_code", "first_name", "last_name", "phone", "national_id"]
    ordering_fields = ["last_name", "first_name", "member_code", "date_joined"]

    def get_queryset(self):
        return super().get_queryset().select_related("shg")

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        """Register many members at once: {shg, members: [{first_name, last_name, phone}]}. All or nothing."""
        payload = BulkMembersInput(data=request.data)
        payload.is_valid(raise_exception=True)
        shg = payload.validated_data["shg"]
        require_shg_access(request.user, shg.id)
        created = []
        with db_transaction.atomic():
            prefix = f"{shg.code}-M"
            used = [int(c[len(prefix):]) for c in Member.objects.filter(member_code__startswith=prefix)
                    .values_list("member_code", flat=True) if c[len(prefix):].isdigit()]
            n = max(used) if used else 0
            for item in payload.validated_data["members"]:
                n += 1
                m = Member(shg=shg, member_code=f"{prefix}{n:03d}", first_name=item["first_name"].strip(),
                           last_name=item["last_name"].strip(), phone=item["phone"].strip(), gender=item["gender"])
                try:
                    m.full_clean()
                except DjangoValidationError as exc:
                    raise as_drf(exc)
                m.save()
                created.append(m)
            AuditLog.record(request.user, AuditLog.Action.CREATE, shg,
                            {"members_added": [m.member_code for m in created]}, client_ip(request))
        return Response(MemberSerializer(created, many=True).data, status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        """Member dashboard: totals for the cycle, loans, fines and how much they can borrow."""
        member = self.get_object()
        cycle_id = request.query_params.get("cycle")
        cycle = (Cycle.objects.filter(pk=cycle_id, shg=member.shg).first() if cycle_id
                 else member.shg.open_cycle)
        if not cycle:
            raise ValidationError({"cycle": "No cycle found for this member's group."})
        return Response(services.member_summary(member, cycle))


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("user").all()
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filterset_fields = ["shg", "user", "action", "model_label"]
    search_fields = ["object_id", "model_label"]


# =============================================================================
# Step 2 — money
# =============================================================================
class MeetingViewSet(ScopedModelViewSet):
    """
    Weekly gatherings.
    GET  /meetings/{id}/sheet/  -> every member with what to fill in
    POST /meetings/{id}/sheet/  -> save the whole sheet at once
    """

    model = Meeting
    serializer_class = MeetingSerializer
    filterset_fields = ["shg", "cycle", "date"]
    ordering_fields = ["date"]

    def get_queryset(self):
        return super().get_queryset().select_related("shg", "cycle", "recorded_by")

    def extra_save_fields(self):
        return {"recorded_by": self.request.user}

    @action(detail=True, methods=["get", "post"])
    def sheet(self, request, pk=None):
        meeting = self.get_object()
        if request.method == "GET":
            return Response(services.build_meeting_sheet(meeting))

        require_shg_access(request.user, meeting.shg_id)
        payload = SheetInput(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            submission, duplicate = services.save_meeting_sheet(
                meeting=meeting, user=request.user,
                submission_id=payload.validated_data["submission_id"],
                rows=payload.validated_data["rows"],
            )
        except services.SheetErrors as exc:
            raise ValidationError({"rows": exc.errors})
        except DjangoValidationError as exc:
            raise as_drf(exc)
        body = services.build_meeting_sheet(meeting)
        body["saved"] = {"submission_id": str(submission.submission_id), "duplicate": duplicate,
                         "transactions": submission.transaction_count, "fines": submission.fine_count}
        return Response(body, status=http.HTTP_200_OK if duplicate else http.HTTP_201_CREATED)


class LoanViewSet(ScopedModelViewSet):
    """
    ?status=open|overdue|paid|cancelled   ?member=   ?shg=
    ?late_fine_missing=true  -> overdue loans with no late-loan fine recorded
    """

    model = Loan
    serializer_class = LoanSerializer
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["shg", "member", "cycle"]
    ordering_fields = ["issue_date", "due_date", "principal"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("member", "shg").with_balances()
        p = self.request.query_params
        status_param = p.get("status")
        if status_param == "open":
            qs = qs.filter(cancelled_at__isnull=True, outstanding_total__gt=0)
        elif status_param == "overdue":
            qs = qs.filter(cancelled_at__isnull=True, outstanding_total__gt=0, due_date__lt=timezone.localdate())
        elif status_param == "paid":
            qs = qs.filter(cancelled_at__isnull=True, outstanding_total__lte=0)
        elif status_param == "cancelled":
            qs = qs.filter(cancelled_at__isnull=False)
        if p.get("late_fine_missing") == "true":
            qs = qs.filter(cancelled_at__isnull=True, outstanding_total__gt=0,
                           due_date__lt=timezone.localdate()).exclude(
                fines__reason=Fine.Reason.LATE_LOAN, fines__cancelled_at__isnull=True)
        return qs

    def create(self, request, *args, **kwargs):
        s = LoanCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        member = d["member"]
        require_shg_access(request.user, member.shg_id)
        if d["over_limit_reason"] and not request.user.is_admin:
            raise PermissionDenied("Only an administrator can approve a loan above the member's limit.")
        try:
            loan = services.issue_loan(shg=member.shg, member=member, principal=d["principal"],
                                       issue_date=d["issue_date"], user=request.user, meeting=d.get("meeting"),
                                       purpose=d["purpose"], over_limit_reason=d["over_limit_reason"])
        except DjangoValidationError as exc:
            raise as_drf(exc)
        loan = self.get_queryset().get(pk=loan.pk)
        return Response(LoanSerializer(loan).data, status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated, IsAdmin])
    def cancel(self, request, pk=None):
        """Admin only: undo a loan given by mistake (only if nothing has been paid on it)."""
        loan = self.get_object()
        s = ReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.cancel_loan(loan, request.user, s.validated_data["reason"])
        except DjangoValidationError as exc:
            raise as_drf(exc)
        return Response(LoanSerializer(self.get_queryset().get(pk=loan.pk)).data)


class FineViewSet(ScopedModelViewSet):
    """?unpaid=true  ?member=  ?reason=LATE_LOAN"""

    model = Fine
    serializer_class = FineSerializer
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["shg", "member", "reason", "loan", "cycle"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("member").with_paid()
        if self.request.query_params.get("unpaid") == "true":
            qs = qs.filter(cancelled_at__isnull=True, paid_total__lt=F("amount"))
        return qs

    def shg_id_for(self, validated_data, instance=None):
        return validated_data["member"].shg_id

    def extra_save_fields(self):
        return {"recorded_by": self.request.user}

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a fine recorded by mistake. Only if nothing has been paid on it."""
        fine = self.get_object()
        require_shg_access(request.user, fine.shg_id)
        s = ReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if fine.cancelled_at:
            raise ValidationError({"fine": "Already cancelled."})
        if fine.paid:
            raise ValidationError({"fine": "This fine has payments. Reverse them first."})
        fine.cancelled_at = timezone.now()
        fine.save(update_fields=["cancelled_at", "updated_at"])
        AuditLog.record(request.user, AuditLog.Action.UPDATE, fine, {"cancelled": True,
                        "reason": s.validated_data["reason"]}, client_ip(request))
        return Response(FineSerializer(self.get_queryset().get(pk=fine.pk)).data)


class TransactionViewSet(ScopedModelViewSet):
    """
    The ledger. Read it here; most entries are created by the weekly sheet and loans.
    POST here only for group expenses and social-fund payouts.
    POST /transactions/{id}/reverse/ {reason} to correct a mistake.
    """

    model = Transaction
    serializer_class = TransactionSerializer
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["shg", "cycle", "member", "meeting", "type", "loan", "fine", "is_reversal"]
    search_fields = ["description", "reference", "member__first_name", "member__last_name"]
    ordering_fields = ["date", "created_at", "amount"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("member", "recorded_by", "reversed_by")
        p = self.request.query_params
        if p.get("date_from"):
            qs = qs.filter(date__gte=p["date_from"])
        if p.get("date_to"):
            qs = qs.filter(date__lte=p["date_to"])
        return qs

    def create(self, request, *args, **kwargs):
        s = DirectTransactionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        require_shg_access(request.user, d["shg"].id)
        tx_date = d.get("date") or timezone.localdate()
        try:
            tx = Transaction(shg=d["shg"], cycle=Cycle.for_date(d["shg"], tx_date), date=tx_date, type=d["type"],
                             amount=d["amount"], member=d.get("member"), expense_category=d["expense_category"],
                             description=d["description"], carried_by=d["carried_by"].strip(), recorded_by=request.user)
            tx.full_clean()
            tx.save()
        except DjangoValidationError as exc:
            raise as_drf(exc)
        AuditLog.record(request.user, AuditLog.Action.CREATE, tx, snapshot(tx), client_ip(request))
        return Response(TransactionSerializer(tx).data, status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        tx = self.get_object()
        require_shg_access(request.user, tx.shg_id)
        s = ReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            rev = tx.reverse(request.user, s.validated_data["reason"])
        except DjangoValidationError as exc:
            raise as_drf(exc)
        return Response(TransactionSerializer(rev).data, status=http.HTTP_201_CREATED)


class PeriodClosingViewSet(ScopedModelViewSet):
    """Admin closes a month for a group; nothing can then be dated inside it."""

    model = PeriodClosing
    serializer_class = PeriodClosingSerializer
    admin_only_write = True
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["shg", "year", "month"]

    def extra_save_fields(self):
        return {"closed_by": self.request.user}


# =============================================================================
# Step 5 - dashboards and reports
# =============================================================================
from django.http import HttpResponse  # noqa: E402
from django.utils.text import slugify  # noqa: E402
from rest_framework.views import APIView  # noqa: E402

from . import reports  # noqa: E402
from .pdf import build_pdf  # noqa: E402


class ReportParams:
    """?shg=<id>  ?year=2026  ?month=1..12  or  ?date_from=2026-03-01&date_to=2026-03-31 (dates win)"""

    @staticmethod
    def read(request):
        q = request.query_params
        groups = SHG.objects.for_user(request.user)
        if q.get("shg"):
            groups = groups.filter(pk=q["shg"])
            if not groups.exists():
                raise NotFound("Group not found.")
        try:
            year = int(q.get("year") or timezone.localdate().year)
            month = int(q["month"]) if q.get("month") else None
            date_from = datetime.date.fromisoformat(q["date_from"]) if q.get("date_from") else None
            date_to = datetime.date.fromisoformat(q["date_to"]) if q.get("date_to") else None
        except ValueError:
            raise ValidationError({"period": "Use numbers for year/month and YYYY-MM-DD for dates."})
        if month is not None and not 1 <= month <= 12:
            raise ValidationError({"month": "Month must be 1 to 12."})
        if not 2000 <= year <= 2100:
            raise ValidationError({"year": "Year out of range."})
        if date_from and date_to and date_from > date_to:
            raise ValidationError({"date_to": "The end date is before the start date."})
        return {"groups": groups, "year": year, "month": month, "date_from": date_from, "date_to": date_to}


class ReportSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(reports.build_summary(**ReportParams.read(request)))


class ReportPdfView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        p = ReportParams.read(request)
        summary = reports.build_summary(**p)
        if len(summary["groups"]) == 1:
            name = summary["groups"][0]["name"]
            title = f"Raporo y'itsinda (Group report) - {name}"
        else:
            name = "all-groups"
            title = "Raporo y'amatsinda yose (All groups report)"
        pdf = build_pdf(summary, title, str(request.user))
        AuditLog.record(request.user, AuditLog.Action.CREATE, request.user,
                        {"report_pdf": name, "period": summary["period"]["label"]}, client_ip(request))
        if p["date_from"] or p["date_to"]:
            stamp = f"{p['date_from'] or ''}_{p['date_to'] or ''}"
        else:
            month_part = f"-{p['month']:02d}" if p["month"] else ""
            stamp = f"{p['year']}{month_part}"
        filename = f"shg-report-{slugify(name)}-{stamp}.pdf"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

# =============================================================================
# Excel: report download, import template, import
# =============================================================================
from rest_framework.parsers import FormParser, MultiPartParser  # noqa: E402

from . import imports  # noqa: E402
from .excel import build_template, build_xlsx  # noqa: E402

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ReportXlsxView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        p = ReportParams.read(request)
        summary = reports.build_summary(**p)
        name = summary["groups"][0]["name"] if len(summary["groups"]) == 1 else "all-groups"
        title = f"Raporo (Report) - {name}"
        if p["date_from"] or p["date_to"]:
            stamp = f"{p['date_from'] or ''}_{p['date_to'] or ''}"
        else:
            month_part = f"-{p['month']:02d}" if p["month"] else ""
            stamp = f"{p['year']}{month_part}"
        AuditLog.record(request.user, AuditLog.Action.CREATE, request.user,
                        {"report_xlsx": name, "period": summary["period"]["label"]}, client_ip(request))
        response = HttpResponse(build_xlsx(summary, title, str(request.user)), content_type=XLSX)
        response["Content-Disposition"] = f'attachment; filename="shg-report-{slugify(name)}-{stamp}.xlsx"'
        return response


class ImportTemplateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        response = HttpResponse(build_template(), content_type=XLSX)
        response["Content-Disposition"] = 'attachment; filename="shg-import-template.xlsx"'
        return response


class ImportView(APIView):
    """POST file=<xlsx> shg=<id> dry_run=true|false. Admin only: it writes history in bulk."""

    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        f = request.FILES.get("file")
        if not f:
            raise ValidationError({"file": "Choose an .xlsx file."})
        if f.size > 5 * 1024 * 1024:
            raise ValidationError({"file": "The file is larger than 5 MB."})
        shg = SHG.objects.filter(pk=request.data.get("shg")).first()
        if not shg:
            raise ValidationError({"shg": "Choose a group."})
        dry_run = str(request.data.get("dry_run", "true")).lower() != "false"
        try:
            result = imports.import_workbook(f, shg, request.user, dry_run=dry_run)
        except imports.ImportFailed as e:
            return Response({"ok": False, "errors": e.errors, **e.stats}, status=http.HTTP_400_BAD_REQUEST)
        return Response({"ok": True, **result}, status=http.HTTP_200_OK if dry_run else http.HTTP_201_CREATED)