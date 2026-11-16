from rest_framework.permissions import BasePermission

from apps.accounts.models import User


class IsModerationStaff(BasePermission):
    message = "moderation_staff_required"

    allowed_roles = {
        User.Role.MODERATOR,
        User.Role.SUPPORT,
        User.Role.ADMIN,
        User.Role.SUPERADMIN,
    }

    def has_permission(self, request, view):  # noqa: ARG002
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_staff
            and user.role in self.allowed_roles
            and user.status == User.Status.ACTIVE
        )


class IsFinanceStaff(BasePermission):
    message = "finance_staff_required"
    allowed_roles = {User.Role.FINANCE, User.Role.ADMIN, User.Role.SUPERADMIN}

    def has_permission(self, request, view):  # noqa: ARG002
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_staff
            and user.role in self.allowed_roles
            and user.status == User.Status.ACTIVE
        )
