import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.compliance.models import ConsentRecord
from apps.matching.models import Match, Swipe
from apps.matching.services import eligible_target, record_swipe, undo_pass
from apps.profiles.models import MatchingPreference, Profile
from apps.store.models import Entitlement, Product, Purchase

from .boosts import activate_boost
from .services import candidate_feed


@override_settings(REQUIRE_VERIFICATION_PRE_DISCOVERY=False)
class DiscoverIntegrationTests(TestCase):
    def setUp(self):
        self.me = self.make_profile("me@example.test", "W", 27, 36.82)
        self.other = self.make_profile("other@example.test", "M", 28, 36.83)
        self.client = APIClient()
        self.client.force_authenticate(user=self.me.user)

    def make_profile(self, email, gender, age, longitude):
        user = User.objects.create_user(email=email)
        profile = Profile.objects.create(
            user=user,
            alias="Quiet Comet",
            gender=gender,
            age_years=age,
            cell=Point(longitude, -1.28, srid=4326),
            cell_updated_at=timezone.now(),
            max_distance_km=15,
            min_age_pref=18,
            max_age_pref=40,
        )
        MatchingPreference.objects.create(profile=profile, target_genders=["ALL"])
        for kind in ("location", "sensitive_data", "voice"):
            ConsentRecord.objects.create(user=user, consent_type=kind, version="test", granted=True)
        return profile

    def grant(self, profile, kind, quantity=1):
        product, _ = Product.objects.get_or_create(
            code=kind,
            defaults={"name": kind, "price_kes": 50, "kind": kind},
        )
        purchase = Purchase.objects.create(
            user=profile.user,
            product=product,
            amount_kes=50,
            phone_hash="0" * 64,
            idempotency_key=str(uuid.uuid4()),
            status="completed",
        )
        return Entitlement.objects.create(
            user=profile.user,
            kind=kind,
            quantity=quantity,
            source_purchase=purchase,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_expired_or_invalid_jwt_returns_401_with_bearer_header(self):
        anonymous = APIClient()
        response = anonymous.get("/api/v1/discover/", HTTP_AUTHORIZATION="Bearer invalid-token")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "Bearer")

    def test_feed_filters_and_swipe_share_authoritative_preferences(self):
        self.me.max_age_pref = 30
        self.me.save()
        self.other.age_years = 36
        self.other.save()
        self.assertEqual(candidate_feed(self.me, min_age=18, max_age=100), [])
        response = self.client.patch("/api/v1/me/profile/", {"max_age_pref": 40}, format="json")
        self.assertEqual(response.status_code, 200)
        self.me.refresh_from_db()
        self.assertEqual(candidate_feed(self.me)[0].pk, self.other.pk)
        self.assertIsNotNone(
            record_swipe(self.me, self.other.public_id, "pass", uuid.uuid4()).swipe
        )

    def test_location_missing_is_actionable(self):
        self.me.cell = None
        self.me.save()
        response = self.client.get("/api/v1/discover/")
        self.assertEqual(response.data["error"]["code"], "location_required")

    def test_saved_onboarding_preferences_include_older_adults_and_remain_mutual(self):
        older = self.make_profile("older@example.test", "M", 62, 36.84)
        response = self.client.patch(
            "/api/v1/me/profile/",
            {
                "target_genders": ["M"],
                "min_age_pref": 50,
                "max_age_pref": 100,
                "max_distance_km": 50,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.me.refresh_from_db()
        self.assertEqual([profile.pk for profile in candidate_feed(self.me)], [older.pk])
        older.max_age_pref = 26
        older.save(update_fields=["max_age_pref"])
        self.assertEqual(candidate_feed(self.me), [])

    def test_multiple_gender_selections_and_everyone_control_the_feed(self):
        woman = self.make_profile("woman@example.test", "W", 28, 36.84)
        nonbinary = self.make_profile("nonbinary@example.test", "NB", 29, 36.85)
        response = self.client.patch(
            "/api/v1/me/profile/", {"target_genders": ["W", "NB"]}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.me.refresh_from_db()
        self.assertEqual(
            {profile.pk for profile in candidate_feed(self.me)}, {woman.pk, nonbinary.pk}
        )
        self.client.patch("/api/v1/me/profile/", {"target_genders": ["ALL"]}, format="json")
        self.me.refresh_from_db()
        self.assertEqual(
            {profile.pk for profile in candidate_feed(self.me)},
            {self.other.pk, woman.pk, nonbinary.pk},
        )

    def test_revoked_consent_blocks_feed_and_swipes_and_hides_target(self):
        other_client = APIClient()
        other_client.force_authenticate(user=self.other.user)
        response = other_client.post(
            "/api/v1/me/consents/",
            {
                "type": "sensitive_data",
                "version": "test",
                "granted": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(candidate_feed(self.me), [])
        with self.assertRaisesMessage(ValueError, "profile_not_found"):
            eligible_target(self.me, self.other.public_id)
        with self.assertRaisesMessage(ValueError, "sensitive_data_consent_required"):
            candidate_feed(self.other)

    def test_swipe_retry_is_idempotent_and_match_response_is_available(self):
        record_swipe(self.other, self.me.public_id, "like", uuid.uuid4())
        client_id = uuid.uuid4()
        first = record_swipe(self.me, self.other.public_id, "like", client_id)
        repeated = record_swipe(self.me, self.other.public_id, "like", client_id)
        self.assertEqual(first.match.pk, repeated.match.pk)
        self.assertEqual(Match.objects.count(), 1)
        self.assertEqual(Swipe.objects.filter(from_profile=self.me).count(), 1)

    def test_latest_pass_undo_requires_premium_and_cannot_undo_a_like(self):
        client_id = uuid.uuid4()
        record_swipe(self.me, self.other.public_id, "pass", client_id)
        with self.assertRaisesMessage(ValueError, "premium_required"):
            undo_pass(self.me, client_id)
        self.grant(self.me, "premium")
        undo_pass(self.me, client_id)
        undo_pass(self.me, client_id)
        self.assertEqual(candidate_feed(self.me)[0].pk, self.other.pk)
        next_id = uuid.uuid4()
        record_swipe(self.me, self.other.public_id, "like", next_id)
        with self.assertRaisesMessage(ValueError, "pass_not_found"):
            undo_pass(self.me, next_id)

    def test_out_of_range_or_blocked_profile_cannot_be_swiped(self):
        from apps.safety.models import Block

        Block.objects.create(blocker=self.other, blocked=self.me)
        with self.assertRaisesMessage(ValueError, "profile_not_eligible"):
            eligible_target(self.me, self.other.public_id)
        Block.objects.all().delete()
        self.other.cell = Point(37.82, -1.28, srid=4326)
        self.other.save()
        with self.assertRaisesMessage(ValueError, "profile_not_eligible"):
            eligible_target(self.me, self.other.public_id)

    def test_boost_consumes_once_ranks_first_and_expires(self):
        nearer = self.make_profile("nearer@example.test", "M", 26, 36.821)
        entitlement = self.grant(self.other, "boost", quantity=2)
        activation = uuid.uuid4()
        boost = activate_boost(self.other, activation)
        same = activate_boost(self.other, activation)
        self.assertEqual(boost.pk, same.pk)
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.quantity, 1)
        self.assertEqual(candidate_feed(self.me)[0].pk, self.other.pk)
        boost.expires_at = timezone.now() - timedelta(seconds=1)
        boost.save()
        self.assertEqual(candidate_feed(self.me)[0].pk, nearer.pk)

    @patch("apps.discovery.views.media_store")
    def test_details_never_return_identity_or_coordinates(self, store):
        store.return_value = None
        response = self.client.get(f"/api/v1/discover/{self.other.public_id}/")
        self.assertEqual(response.status_code, 200)
        for key in ("cell", "lat", "lon", "gender", "target_genders", "email", "real_avatar_url"):
            self.assertNotIn(key, response.data)

    @patch("apps.discovery.views.media_store")
    def test_audio_is_not_signed_after_voice_consent_withdrawal(self, store):
        self.other.audio_key = "voice/processed.m4a"
        self.other.save()
        ConsentRecord.objects.filter(user=self.other.user, consent_type="voice").update(
            revoked_at=timezone.now()
        )
        response = self.client.get("/api/v1/discover/")
        self.assertIsNone(response.data["items"][0]["audio_url"])
        store.return_value.presign_private.assert_not_called()
