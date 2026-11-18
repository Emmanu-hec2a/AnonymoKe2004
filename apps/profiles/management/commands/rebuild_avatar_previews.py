from django.core.management.base import BaseCommand, CommandError

from apps.profiles.models import MediaAsset
from apps.profiles.tasks_media import refresh_avatar_preview


class Command(BaseCommand):
    help = (
        "Queue softer blurred previews for approved photos; originals and visibility stay intact."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 1000:
            raise CommandError("limit must be between 1 and 1000")
        assets = (
            MediaAsset.objects.filter(kind="avatar", status="ready", user__status="active")
            .exclude(original_key="")
            .exclude(derived_key="")
            .order_by("created_at")
            .values_list("pk", flat=True)[:limit]
        )
        if options["dry_run"]:
            self.stdout.write(f"Eligible approved previews: {len(assets)}")
            return
        queued = 0
        for asset_id in assets:
            try:
                refresh_avatar_preview.delay(str(asset_id))
            except Exception as error:  # noqa: BLE001 - no provider secrets in command output
                raise CommandError(f"Preview queue unavailable after {queued} requests") from error
            queued += 1
        self.stdout.write(f"Queued approved preview refreshes: {queued}")
