from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from accounts.models import User
from .models import SHG, AuditLog, Cycle, LeaderAssignment, Member


class CleanModelSerializer(serializers.ModelSerializer):
    """Runs the model's own clean() rules, so the API and Django admin enforce the same checks."""

    def _full_clean(self, instance):
        try:
            instance.full_clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(getattr(e, "message_dict", {"non_field_errors": e.messages}))

    @transaction.atomic
    def create(self, validated_data):
        instance = self.Meta.model(**validated_data)
        self._full_clean(instance)
        instance.save()
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        for k, v in validated_data.items():
            setattr(instance, k, v)
        self._full_clean(instance)
        instance.save()
        return instance


def next_shg_code():
    numbers = [int(c[3:]) for c in SHG.objects.filter(code__startswith="SHG").values_list("code", flat=True)
               if c[3:].isdigit()]
    return f"SHG{(max(numbers) + 1) if numbers else 1:03d}"


class SHGSerializer(CleanModelSerializer):
    code = serializers.CharField(required=False, allow_blank=True, max_length=10)
    member_count = serializers.SerializerMethodField()
    current_leader = serializers.SerializerMethodField()
    open_cycle = serializers.SerializerMethodField()

    class Meta:
        model = SHG
        fields = ["id", "code", "name", "location", "formation_date", "status", "rules_note",
                  "member_count", "current_leader", "open_cycle", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_code(self, value):
        if value and SHG.objects.filter(code=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError("This group code is already used.")
        return value

    def validate_name(self, value):
        value = value.strip()
        if SHG.objects.filter(name__iexact=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError("A group with this name already exists.")
        return value

    def create(self, validated_data):
        if not validated_data.get("code"):
            validated_data["code"] = next_shg_code()
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "code" in validated_data and not validated_data["code"]:
            validated_data.pop("code")
        return super().update(instance, validated_data)

    def get_member_count(self, obj):
        if hasattr(obj, "member_count"):
            return obj.member_count
        return obj.members.filter(status=Member.Status.ACTIVE).count()

    def get_current_leader(self, obj):
        leader = obj.current_leader
        return {"id": leader.id, "name": str(leader)} if leader else None

    def get_open_cycle(self, obj):
        c = obj.open_cycle
        return {"id": c.id, "name": c.name} if c else None


class CycleSerializer(CleanModelSerializer):
    shg_code = serializers.CharField(source="shg.code", read_only=True)

    class Meta:
        model = Cycle
        fields = ["id", "shg", "shg_code", "name", "start_date", "end_date", "share_price",
                  "ingoboka_weekly", "mutuelle_weekly", "interest_rate_percent", "loan_term_months",
                  "loan_multiplier", "fines_in_profit", "opening_cash", "status", "closed_at", "closed_by"]
        read_only_fields = ["status", "closed_at", "closed_by"]

    def validate(self, attrs):
        """Share price and interest rate are locked once money is recorded, or old totals would change."""
        c = self.instance
        if c and c.transactions.exists():
            for field in ("share_price", "interest_rate_percent", "start_date", "shg"):
                if field in attrs and attrs[field] != getattr(c, field):
                    raise serializers.ValidationError(
                        {field: "Cannot change this after money has been recorded in the cycle."})
        return attrs


class LeaderAssignmentSerializer(CleanModelSerializer):
    leader_name = serializers.CharField(source="leader.__str__", read_only=True)
    shg_code = serializers.CharField(source="shg.code", read_only=True)
    leader = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role=User.Role.LEADER, is_active=True))

    class Meta:
        model = LeaderAssignment
        fields = ["id", "shg", "shg_code", "leader", "leader_name", "start_date", "end_date", "assigned_by"]
        read_only_fields = ["assigned_by"]


def next_member_code(shg):
    prefix = f"{shg.code}-M"
    numbers = [
        int(code[len(prefix):])
        for code in Member.objects.filter(member_code__startswith=prefix).values_list("member_code", flat=True)
        if code[len(prefix):].isdigit()
    ]
    return f"{prefix}{(max(numbers) + 1) if numbers else 1:03d}"


class MemberSerializer(CleanModelSerializer):
    member_code = serializers.CharField(required=False, allow_blank=True, max_length=20)
    shg_code = serializers.CharField(source="shg.code", read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Member
        fields = ["id", "shg", "shg_code", "member_code", "full_name", "first_name", "last_name", "gender",
                  "date_of_birth", "phone", "date_joined", "status", "notes", "national_id", "cell",
                  "sector", "is_household_head", "household_size", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_member_code(self, value):
        if value and Member.objects.filter(member_code=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError("This member code is already used.")
        return value

    def create(self, validated_data):
        if not validated_data.get("member_code"):
            validated_data["member_code"] = next_member_code(validated_data["shg"])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "member_code" in validated_data and not validated_data["member_code"]:
            validated_data.pop("member_code")
        return super().update(instance, validated_data)


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.__str__", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "user", "user_name", "shg", "action", "model_label", "object_id",
                  "changes", "ip_address", "created_at"]


# =============================================================================
# Step 2 — money
# =============================================================================
from django.utils import timezone  # noqa: E402

from .models import Fine, Loan, Meeting, PeriodClosing, Transaction  # noqa: E402


class MeetingSerializer(serializers.ModelSerializer):
    shg_code = serializers.CharField(source="shg.code", read_only=True)
    cycle_name = serializers.CharField(source="cycle.name", read_only=True)
    recorded_by_name = serializers.CharField(source="recorded_by.__str__", read_only=True)
    submissions = serializers.IntegerField(source="submissions.count", read_only=True)

    class Meta:
        model = Meeting
        fields = ["id", "shg", "shg_code", "cycle", "cycle_name", "date", "location", "notes",
                  "recorded_by", "recorded_by_name", "submissions", "created_at"]
        read_only_fields = ["cycle", "recorded_by", "created_at"]

    def validate(self, attrs):
        shg = attrs.get("shg") or self.instance.shg
        d = attrs.get("date") or self.instance.date
        if self.instance and ("shg" in attrs or "date" in attrs):
            raise serializers.ValidationError("A meeting's group and date cannot be changed.")
        if not self.instance:
            try:
                attrs["cycle"] = Cycle.for_date(shg, d)
            except DjangoValidationError as e:
                raise serializers.ValidationError(e.message_dict)
            if Meeting.objects.filter(shg=shg, date=d).exists():
                raise serializers.ValidationError({"date": "This group already has a meeting on that date."})
        return attrs

    def create(self, validated_data):
        m = Meeting(**validated_data)
        try:
            m.full_clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(getattr(e, "message_dict", {"non_field_errors": e.messages}))
        m.save()
        return m


# ---- weekly sheet input ------------------------------------------------------
class LoanPaymentInput(serializers.Serializer):
    loan = serializers.PrimaryKeyRelatedField(queryset=Loan.objects.all())
    returned = serializers.IntegerField(min_value=0, required=False, default=0)
    interest = serializers.IntegerField(min_value=0, required=False, default=0)


class FinePaymentInput(serializers.Serializer):
    fine = serializers.PrimaryKeyRelatedField(queryset=Fine.objects.all())
    amount = serializers.IntegerField(min_value=1)


class NewFineInput(serializers.Serializer):
    reason = serializers.ChoiceField(choices=Fine.Reason.choices)
    amount = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    loan = serializers.PrimaryKeyRelatedField(queryset=Loan.objects.all(), required=False, allow_null=True)
    paid_now = serializers.BooleanField(required=False, default=False)


class SheetRowInput(serializers.Serializer):
    member = serializers.PrimaryKeyRelatedField(queryset=Member.objects.all())
    present = serializers.BooleanField(required=False, allow_null=True, default=None)
    shares = serializers.IntegerField(min_value=0, required=False, default=0)
    ingoboka = serializers.IntegerField(min_value=0, required=False, default=0)
    mutuelle = serializers.IntegerField(min_value=0, required=False, default=0)
    loan_payments = LoanPaymentInput(many=True, required=False, default=list)
    fine_payments = FinePaymentInput(many=True, required=False, default=list)
    new_fines = NewFineInput(many=True, required=False, default=list)


class SheetInput(serializers.Serializer):
    submission_id = serializers.UUIDField()
    rows = SheetRowInput(many=True, allow_empty=False)


# ---- loans -------------------------------------------------------------------------
class LoanSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.full_name", read_only=True)
    member_code = serializers.CharField(source="member.member_code", read_only=True)
    shg_code = serializers.CharField(source="shg.code", read_only=True)
    returned = serializers.SerializerMethodField()
    interest_paid = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    interest_due_on_full_return = serializers.IntegerField(read_only=True)
    has_late_fine = serializers.BooleanField(read_only=True)

    class Meta:
        model = Loan
        fields = ["id", "shg", "shg_code", "cycle", "member", "member_code", "member_name", "meeting",
                  "principal", "interest_rate_percent", "issue_date", "due_date", "purpose",
                  "returned", "interest_paid", "outstanding", "interest_due_on_full_return", "status",
                  "has_late_fine", "over_limit_approved_by", "over_limit_reason", "cancelled_at",
                  "cancel_reason", "recorded_by", "created_at"]
        read_only_fields = fields

    def _v(self, obj, annotated, prop):
        return getattr(obj, annotated) if hasattr(obj, annotated) else getattr(obj, prop)

    def get_returned(self, obj):
        return self._v(obj, "returned_total", "returned")

    def get_interest_paid(self, obj):
        return self._v(obj, "interest_total", "interest_paid")

    def get_outstanding(self, obj):
        return self._v(obj, "outstanding_total", "outstanding")

    def get_status(self, obj):
        returned = self.get_returned(obj)
        return Loan.compute_status(due_date=obj.due_date, outstanding=obj.principal - returned,
                                   returned=returned, cancelled_at=obj.cancelled_at)


class LoanCreateSerializer(serializers.Serializer):
    member = serializers.PrimaryKeyRelatedField(queryset=Member.objects.all())
    principal = serializers.IntegerField(min_value=1)
    issue_date = serializers.DateField(required=False)
    meeting = serializers.PrimaryKeyRelatedField(queryset=Meeting.objects.all(), required=False, allow_null=True)
    purpose = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    over_limit_reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)

    def validate(self, attrs):
        meeting = attrs.get("meeting")
        if meeting:
            if meeting.shg_id != attrs["member"].shg_id:
                raise serializers.ValidationError({"meeting": "Meeting belongs to another group."})
            attrs["issue_date"] = meeting.date
        attrs.setdefault("issue_date", timezone.localdate())
        return attrs


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)


# ---- fines ---------------------------------------------------------------------------
class FineSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.full_name", read_only=True)
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)
    paid = serializers.SerializerMethodField()
    remaining = serializers.SerializerMethodField()

    class Meta:
        model = Fine
        fields = ["id", "shg", "cycle", "member", "member_name", "meeting", "loan", "reason", "reason_display",
                  "reason_note", "amount", "paid", "remaining", "issued_date", "recorded_by", "cancelled_at",
                  "created_at"]
        read_only_fields = ["shg", "cycle", "recorded_by", "cancelled_at", "created_at"]
        extra_kwargs = {"issued_date": {"required": False}}

    def get_paid(self, obj):
        return obj.paid_total if hasattr(obj, "paid_total") else obj.paid

    def get_remaining(self, obj):
        return obj.amount - self.get_paid(obj)

    def validate(self, attrs):
        member = attrs["member"]
        attrs["shg"] = member.shg
        attrs.setdefault("issued_date", timezone.localdate())
        try:
            attrs["cycle"] = Cycle.for_date(member.shg, attrs["issued_date"])
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        return attrs

    def create(self, validated_data):
        f = Fine(**validated_data)
        try:
            f.full_clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(getattr(e, "message_dict", {"non_field_errors": e.messages}))
        f.save()
        return f


# ---- ledger ------------------------------------------------------------------------------
class TransactionSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    member_name = serializers.CharField(source="member.full_name", read_only=True, default=None)
    recorded_by_name = serializers.CharField(source="recorded_by.__str__", read_only=True)
    signed_amount = serializers.SerializerMethodField()
    reversed = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = ["id", "shg", "cycle", "meeting", "member", "member_name", "date", "type", "type_display",
                  "amount", "signed_amount", "share_count", "loan", "fine", "expense_category", "description",
                  "reference", "carried_by", "is_reversal", "reverses", "reversed", "recorded_by", "recorded_by_name",
                  "approved_by", "created_at"]
        read_only_fields = fields

    def get_signed_amount(self, obj):
        return -obj.amount if obj.is_reversal else obj.amount

    def get_reversed(self, obj):
        return hasattr(obj, "reversed_by")


class DirectTransactionSerializer(serializers.Serializer):
    """Entries made outside the weekly sheet: group expenses and social-fund payouts."""

    shg = serializers.PrimaryKeyRelatedField(queryset=SHG.objects.all())
    type = serializers.ChoiceField(choices=[(Transaction.Type.EXPENSE, "Group expense"),
                                            (Transaction.Type.INGOBOKA_OUT, "Ingoboka payout"),
                                            (Transaction.Type.OTHER_INCOME, "Other money in"),
                                            (Transaction.Type.BANK_DEPOSIT, "Taken to the bank")])
    date = serializers.DateField(required=False)
    amount = serializers.IntegerField(min_value=1)
    member = serializers.PrimaryKeyRelatedField(queryset=Member.objects.all(), required=False, allow_null=True)
    expense_category = serializers.ChoiceField(choices=Transaction.ExpenseCategory.choices, required=False,
                                               allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    carried_by = serializers.CharField(required=False, allow_blank=True, default="", max_length=120)


class PeriodClosingSerializer(serializers.ModelSerializer):
    shg_code = serializers.CharField(source="shg.code", read_only=True)
    closed_by_name = serializers.CharField(source="closed_by.__str__", read_only=True)

    class Meta:
        model = PeriodClosing
        fields = ["id", "shg", "shg_code", "year", "month", "closed_by", "closed_by_name", "closed_at"]
        read_only_fields = ["closed_by", "closed_at"]

    def validate(self, attrs):
        today = timezone.localdate()
        if (attrs["year"], attrs["month"]) > (today.year, today.month):
            raise serializers.ValidationError({"month": "You cannot close a month that has not happened yet."})
        if PeriodClosing.objects.filter(shg=attrs["shg"], year=attrs["year"], month=attrs["month"]).exists():
            raise serializers.ValidationError({"month": "That month is already closed."})
        return attrs


class BulkMemberItem(serializers.Serializer):
    first_name = serializers.CharField(max_length=60)
    last_name = serializers.CharField(max_length=60)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    gender = serializers.ChoiceField(choices=Member.Gender.choices, required=False, allow_blank=True, default="")


class BulkMembersInput(serializers.Serializer):
    shg = serializers.PrimaryKeyRelatedField(queryset=SHG.objects.all())
    members = BulkMemberItem(many=True, allow_empty=False)

    def validate_members(self, value):
        if len(value) > 200:
            raise serializers.ValidationError("Add at most 200 members at once.")
        return value
