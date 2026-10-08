from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User


class LoginSerializer(TokenObtainPairSerializer):
    """Adds role and name to the login response so React knows which screens to show."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = MeSerializer(self.user).data
        return data


class MeSerializer(serializers.ModelSerializer):
    groups_led = serializers.SerializerMethodField()
    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "full_name", "first_name", "last_name", "email", "phone", "role", "groups_led"]
        read_only_fields = fields

    def get_groups_led(self, user):
        from shg.models import LeaderAssignment

        rows = LeaderAssignment.objects.filter(leader=user, end_date__isnull=True).select_related("shg")
        return [{"id": a.shg_id, "code": a.shg.code, "name": a.shg.name} for a in rows]


class UserSerializer(serializers.ModelSerializer):
    """Admin-only user management."""

    password = serializers.CharField(write_only=True, required=False, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "phone", "role",
                  "is_active", "last_login", "date_joined", "password"]
        read_only_fields = ["last_login", "date_joined"]

    def validate(self, attrs):
        if not self.instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": "A password is required for a new user."})
        if attrs.get("password"):
            validate_password(attrs["password"])
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField()

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError({"old_password": "Current password is wrong."})
        validate_password(attrs["new_password"], user)
        return attrs
