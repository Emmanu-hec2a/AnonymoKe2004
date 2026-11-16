from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.chat.models import Message
from apps.matching.models import Match
from apps.profiles.models import Profile

from .models import Block, Report


def validate_evidence_message_ids(
    *, reporter: User, reported: User, message_ids: list[str]
) -> list[str]:
    """Return only message IDs from a match between the two reporting parties."""
    if not message_ids:
        return []
    reporter_profile = Profile.objects.filter(user=reporter).first()
    reported_profile = Profile.objects.filter(user=reported).first()
    if not reporter_profile or not reported_profile:
        raise ValueError("evidence_invalid")
    match_ids = Match.objects.filter(
        Q(profile_a=reporter_profile, profile_b=reported_profile)
        | Q(profile_a=reported_profile, profile_b=reporter_profile)
    ).values_list("id", flat=True)
    valid = list(
        Message.objects.filter(id__in=message_ids, match_id__in=match_ids).values_list(
            "id", flat=True
        )
    )
    if {str(value) for value in valid} != set(message_ids):
        raise ValueError("evidence_invalid")
    return [str(value) for value in valid]


@transaction.atomic
def register_report(
    *,
    reporter: User,
    reported: User,
    reason: str,
    note: str = "",
    evidence_message_ids: list[str] | None = None,
) -> Report:
    if reporter.pk == reported.pk:
        raise ValueError("cannot_report_self")
    evidence = validate_evidence_message_ids(
        reporter=reporter, reported=reported, message_ids=evidence_message_ids or []
    )
    report, _ = Report.objects.get_or_create(
        reporter=reporter,
        reported=reported,
        reason=reason,
        defaults={"note": note, "evidence_message_ids": evidence},
    )
    if report.note != note or report.evidence_message_ids != evidence:
        report.note = note
        report.evidence_message_ids = evidence
        report.save(update_fields=["note", "evidence_message_ids", "updated_at"])
    if (
        reason in {Report.Reason.SCAM, Report.Reason.SOLICITATION}
        and settings.AUTO_SUSPEND_SCAM_REPORTS
    ):
        count = (
            Report.objects.filter(
                reported=reported,
                reason__in=[Report.Reason.SCAM, Report.Reason.SOLICITATION],
                status=Report.Status.OPEN,
            )
            .values("reporter_id")
            .distinct()
            .count()
        )
        if count >= settings.AUTO_SUSPEND_REPORT_THRESHOLD:
            User.objects.filter(pk=reported.pk, status=User.Status.ACTIVE).update(
                status=User.Status.SUSPENDED
            )
    if reason == Report.Reason.UNDERAGE:
        User.objects.filter(pk=reported.pk).update(status=User.Status.SUSPENDED)
    return report


@transaction.atomic
def block_profile(*, blocker: Profile, blocked: Profile) -> Block:
    if blocker.pk == blocked.pk:
        raise ValueError("cannot_block_self")
    block, _ = Block.objects.get_or_create(blocker=blocker, blocked=blocked)
    Match.objects.filter(
        Q(profile_a=blocker, profile_b=blocked) | Q(profile_a=blocked, profile_b=blocker),
        state__in=[Match.State.MASKED, Match.State.UNMASKED],
    ).update(
        state=Match.State.CLOSED,
        closed_by=blocker,
        a_unmask_consent_at=None,
        b_unmask_consent_at=None,
        updated_at=timezone.now(),
    )
    return block
