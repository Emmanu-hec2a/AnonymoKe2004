import uuid
from unittest.mock import patch

from django.test import TestCase

from apps.matching.models import Swipe
from apps.matching.services import record_swipe
from apps.safety.models import Block

from . import tests as fixtures
from .services import candidate_feed


class BrowsingPaginationTests(TestCase):
    make_profile = fixtures.DiscoverIntegrationTests.make_profile
    setUp = fixtures.DiscoverIntegrationTests.setUp

    def populate(self):
        self.enterContext(patch("apps.discovery.views.media_store", return_value=None))
        for number in range(44):
            self.make_profile(f"page{number}@example.test", "M", 28, 36.83)

    def test_all_profiles_can_be_browsed_without_creating_swipes(self):
        self.populate()
        cursor = None
        seen = []
        for _ in range(4):
            response = self.client.get("/api/v1/discover/", {"cursor": cursor} if cursor else {})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response["Cache-Control"], "no-store")
            seen.extend(item["profile_id"] for item in response.data["items"])
            cursor = response.data["next_cursor"]
            if cursor is None:
                break
            self.assertNotIn(str(self.me.pk), cursor)
        self.assertEqual(len(seen), 45)
        self.assertEqual(len(set(seen)), 45)
        self.assertFalse(Swipe.objects.exists())

    def test_explicit_decisions_do_not_skip_profiles_on_the_next_page(self):
        self.populate()
        original = candidate_feed(self.me, limit=100)
        first = self.client.get("/api/v1/discover/").data
        record_swipe(self.me, original[0].public_id, "pass", uuid.uuid4())
        second = self.client.get("/api/v1/discover/", {"cursor": first["next_cursor"]})
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(
            [item["profile_id"] for item in second.data["items"]],
            [str(item.public_id) for item in original[20:40]],
        )

    def test_cursor_is_bound_to_account_preferences_and_current_eligibility(self):
        self.populate()
        first = self.client.get("/api/v1/discover/").data
        cursor = first["next_cursor"]
        changed = self.client.get("/api/v1/discover/", {"cursor": cursor, "max_age": 30})
        self.assertEqual(changed.status_code, 400)
        target = candidate_feed(self.me, limit=100)[20]
        Block.objects.create(blocker=target, blocked=self.me)
        second = self.client.get("/api/v1/discover/", {"cursor": cursor})
        self.assertEqual(second.status_code, 200, second.data)
        self.assertNotIn(
            str(target.public_id), [item["profile_id"] for item in second.data["items"]]
        )
        self.client.force_authenticate(self.other.user)
        foreign = self.client.get("/api/v1/discover/", {"cursor": cursor})
        self.assertEqual(foreign.status_code, 400)

    def test_malformed_cursor_is_actionable(self):
        response = self.client.get("/api/v1/discover/", {"cursor": "invalid"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "cursor_invalid")
