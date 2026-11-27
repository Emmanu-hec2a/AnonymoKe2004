import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.compliance.models import ConsentRecord

from . import tests as fixtures
from .lifecycle import acknowledge_alert, resolve_plan, unlink_contact
from .models import DateSession, PanicAlert, SafetyAlertRecipient, SafetyDelivery


class CleanSafetyOverviewTests(TestCase):
    setUp = fixtures.SafetyIntegrationTests.setUp
    user = fixtures.SafetyIntegrationTests.user
    plan = fixtures.SafetyIntegrationTests.plan
    panic = fixtures.SafetyIntegrationTests.panic

    def completed(self, number=0, **values):
        now = timezone.now()
        data = dict(
            user=self.owner,
            trusted_contact_user=self.friend,
            trusted_contact_name="Friend",
            status="safe",
            safe_at=now - timedelta(days=1),
            starts_at=now - timedelta(days=1, hours=3),
            check_in_due_at=now - timedelta(days=1),
            venue_label=f"Cafe {number}",
        )
        data.update(values)
        return DateSession.objects.create(**data)

    def test_repeated_safe_checkin_archives_once_and_keeps_one_temporary_notice(self):
        alert = self.panic()
        for _ in range(20):
            resolve_plan(self.owner, alert.date_session_id, safe=True)
        self.assertEqual(SafetyDelivery.objects.filter(event_type="safety.safe").count(), 1)
        for user in (self.owner, self.friend):
            self.client.force_authenticate(user)
            overview = self.client.get(self.base, {"view": "active"}).data
            self.assertIsNone(overview["active_date"])
            self.assertEqual(overview["panic_alerts"], [])
            self.assertEqual(overview["incoming_alerts"], [])
            self.assertEqual(overview["shared_plans"], [])
            self.assertEqual(overview["history_count"], 1)
            notice = overview["recent_completion"]
            self.assertEqual(notice["session"]["id"], str(alert.date_session_id))
            self.assertGreater(notice["expires_in_seconds"], 0)
            self.assertLessEqual(notice["expires_in_seconds"], 300)
            history = self.client.get(self.base + "history/", {"paged": "1"})
            self.assertEqual(history.status_code, 200)
            self.assertEqual(history.data["total_count"], 1)
            self.assertIsNotNone(history.data["items"][0]["safe_at"])
            self.assertEqual(history["Cache-Control"], "no-store")

    def test_twenty_completed_plans_leave_no_completed_cards_on_the_main_tab(self):
        for i in range(20):
            plan = self.completed(i)
            alert = PanicAlert.objects.create(
                user=self.owner, date_session=plan, idempotency_key=str(uuid.uuid4())
            )
            SafetyAlertRecipient.objects.create(alert=alert, recipient_user=self.friend)
        self.client.force_authenticate(self.friend)
        overview = self.client.get(self.base, {"view": "active"}).data
        self.assertEqual(overview["history_count"], 20)
        self.assertEqual(overview["incoming_alert_count"], 0)
        self.assertEqual(overview["shared_plan_count"], 0)
        self.assertIsNone(overview["recent_completion"])
        page = self.client.get(self.base + "history/", {"paged": "1"}).data
        self.assertEqual(len(page["items"]), 20)
        self.assertEqual(len({item["id"] for item in page["items"]}), 20)

    def test_acknowledged_panic_remains_active_and_is_not_duplicated_as_a_shared_plan(self):
        alert = self.panic()
        acknowledge_alert(self.friend, alert.recipients.get().pk)
        self.client.force_authenticate(self.friend)
        overview = self.client.get(self.base, {"view": "active"}).data
        self.assertEqual(overview["incoming_alert_count"], 1)
        self.assertEqual(overview["incoming_alerts"][0]["status"], "acknowledged")
        self.assertEqual(overview["incoming_alerts"][0]["date_session"], str(alert.date_session_id))
        self.assertEqual(overview["shared_plan_count"], 0)
        self.assertEqual(overview["history_count"], 0)
        active = self.client.get(self.base + "alerts/", {"paged": "1", "active": "1"})
        self.assertEqual(active.data["total_count"], 1)

    def test_recent_confirmation_expires_but_history_does_not(self):
        self.completed(safe_at=timezone.now() - timedelta(minutes=6))
        overview = self.client.get(self.base, {"view": "active"}).data
        self.assertIsNone(overview["recent_completion"])
        self.assertEqual(overview["history_count"], 1)

    def test_history_permissions_and_unlink_revoke_shared_access(self):
        self.completed()
        self.client.force_authenticate(self.stranger)
        self.assertEqual(
            self.client.get(self.base + "history/", {"paged": "1"}).data["total_count"], 0
        )
        self.client.force_authenticate(self.friend)
        page = self.client.get(self.base + "history/", {"paged": "1"}).data
        self.assertEqual(page["total_count"], 1)
        self.assertEqual(page["items"][0]["viewer_role"], "trusted_contact")
        unlink_contact(self.owner)
        self.assertEqual(
            self.client.get(self.base + "history/", {"paged": "1"}).data["total_count"], 0
        )
        self.client.force_authenticate(self.owner)
        page = self.client.get(self.base + "history/", {"paged": "1"}).data
        self.assertEqual(page["total_count"], 1)
        self.assertEqual(page["items"][0]["viewer_role"], "owner")

    def test_completed_history_paginates_and_rejects_another_accounts_cursor(self):
        for i in range(45):
            self.completed(i)
        ids, cursor = [], None
        first = None
        for _ in range(3):
            response = self.client.get(
                self.base + "history/", {"paged": "1", **({"cursor": cursor} if cursor else {})}
            )
            self.assertEqual(response.status_code, 200)
            ids.extend(item["id"] for item in response.data["items"])
            cursor = response.data["next_cursor"]
            first = first or cursor
        self.assertEqual(len(set(ids)), 45)
        self.assertIsNone(cursor)
        self.client.force_authenticate(self.friend)
        response = self.client.get(self.base + "history/", {"paged": "1", "cursor": first})
        self.assertEqual(response.status_code, 400)

    def test_history_respects_revoked_location_consent(self):
        self.completed(
            share_approximate_location=True,
            approximate_area={"latitude": -1.28, "longitude": 36.82, "radius_km": 3},
        )
        ConsentRecord.objects.filter(user=self.owner, consent_type="location").update(
            revoked_at=timezone.now()
        )
        page = self.client.get(self.base + "history/", {"paged": "1"}).data
        self.assertIsNone(page["items"][0]["approximate_area"])

    def test_cleanup_is_routed_to_a_queue_consumed_by_the_deployed_worker(self):
        from config.celery import app

        from .tasks import purge_safety_history

        route = app.amqp.router.route(
            {"queue": purge_safety_history.queue}, purge_safety_history.name
        )
        self.assertEqual(purge_safety_history.queue, "default")
        self.assertEqual(route["queue"].name, "default")

    def test_older_apks_keep_the_legacy_overview_during_rollout(self):
        alert = self.panic()
        resolve_plan(self.owner, alert.date_session_id, safe=True)
        self.client.force_authenticate(self.friend)
        legacy = self.client.get(self.base).data
        focused = self.client.get(self.base, {"view": "active"}).data
        self.assertEqual(legacy["incoming_alerts"][0]["session_status"], "safe")
        self.assertEqual(legacy["shared_plan_count"], 1)
        self.assertEqual(focused["incoming_alerts"], [])
        self.assertEqual(focused["shared_plan_count"], 0)
        self.assertEqual(focused["history_count"], 1)
