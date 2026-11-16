from django.utils import timezone

from .models import ConsentRecord


def has_active_consent(user, consent_type: str) -> bool:
    record = (
        ConsentRecord.objects.filter(
            user=user,
            consent_type=consent_type,
            granted=True,
            revoked_at__isnull=True,
        )
        .order_by("-granted_at")
        .first()
    )
    return bool(record and record.granted_at <= timezone.now())
