from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User

from .lifecycle import accept_invite, issue_invite, save_plan, trigger_panic
from .models import PanicAlert, SafetyAlertRecipient, TrustedContact


class SafetyConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner-race@example.test")
        self.a = User.objects.create_user(email="contact-a@example.test")
        self.b = User.objects.create_user(email="contact-b@example.test")
        self.contact = TrustedContact.objects.create(user=self.owner, contact_name="Friend")
        self.enqueue = patch("apps.safety.tasks.dispatch_safety_delivery.delay").start()
        self.addCleanup(patch.stopall)

    def race(self, callback):
        barrier = Barrier(2)

        def run(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return callback(index)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, [0, 1]))

    def test_simultaneous_invite_redemptions_cannot_overwrite_the_first_recipient(self):
        code, _ = issue_invite(self.owner)

        def redeem(index):
            try:
                accept_invite([self.a, self.b][index], code)
                return "linked"
            except ValueError:
                return "rejected"

        self.assertCountEqual(self.race(redeem), ["linked", "rejected"])
        self.contact.refresh_from_db()
        self.assertIn(self.contact.linked_user_id, [self.a.pk, self.b.pk])
        self.assertEqual(self.contact.invite_code_hash, "")

    def test_simultaneous_panics_with_different_keys_create_one_alert(self):
        self.contact.linked_user = self.a
        self.contact.save()
        now = timezone.now()
        save_plan(
            self.owner,
            {
                "starts_at": now,
                "check_in_due_at": now + timedelta(hours=2),
                "venue_label": "Public cafe",
            },
        )
        results = self.race(lambda index: str(trigger_panic(self.owner, f"panic-{index}")[0].pk))
        self.assertEqual(results[0], results[1])
        self.assertEqual(PanicAlert.objects.count(), 1)
        self.assertEqual(SafetyAlertRecipient.objects.count(), 1)
