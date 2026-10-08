from rest_framework.routers import DefaultRouter

from .views import (AuditLogViewSet, CycleViewSet, FineViewSet, LeaderAssignmentViewSet, LoanViewSet, MeetingViewSet,
                    MemberViewSet, PeriodClosingViewSet, SHGViewSet, TransactionViewSet)

router = DefaultRouter()
router.register("shgs", SHGViewSet, basename="shg")
router.register("cycles", CycleViewSet, basename="cycle")
router.register("leader-assignments", LeaderAssignmentViewSet, basename="leader-assignment")
router.register("members", MemberViewSet, basename="member")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")
router.register("meetings", MeetingViewSet, basename="meeting")
router.register("loans", LoanViewSet, basename="loan")
router.register("fines", FineViewSet, basename="fine")
router.register("transactions", TransactionViewSet, basename="transaction")
router.register("period-closings", PeriodClosingViewSet, basename="period-closing")

from django.urls import path  # noqa: E402

from .views import ImportTemplateView, ImportView, ReportPdfView, ReportSummaryView, ReportXlsxView  # noqa: E402

urlpatterns = router.urls + [
    path("reports/summary/", ReportSummaryView.as_view(), name="report-summary"),
    path("reports/pdf/", ReportPdfView.as_view(), name="report-pdf"),
    path("reports/xlsx/", ReportXlsxView.as_view(), name="report-xlsx"),
    path("imports/template/", ImportTemplateView.as_view(), name="import-template"),
    path("imports/xlsx/", ImportView.as_view(), name="import-xlsx"),
]