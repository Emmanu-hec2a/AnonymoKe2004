import io
import urllib.error
import uuid
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.compliance.models import ConsentRecord
from apps.discovery.models import ProfileBoost
from apps.profiles.models import Profile

from .models import Entitlement, Product, Purchase
from .providers import DarajaPaymentProvider, PaymentProviderError, TransactionQuery
from .services import create_purchase, process_daraja_callback


class RecordingProvider:
    def __init__(self, completed=False):
        self.queries = 0
        self.completed = completed

    def initiate_stk(self, **_):
        from .providers import CheckoutInitiation

        return CheckoutInitiation(checkout_request_id="ws_CO_1", merchant_request_id="m-1")

    def query_transaction(self, *, checkout_request_id):  # noqa: ARG002
        self.queries += 1
        return TransactionQuery(
            completed=self.completed, result_code=0 if self.completed else None, raw={}
        )


def stk_callback(code, desc, amount=None, phone=None, receipt=None):
    callback = {
        "MerchantRequestID": "m-1",
        "CheckoutRequestID": "ws_CO_1",
        "ResultCode": code,
        "ResultDesc": desc,
    }
    if receipt:
        callback["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": receipt},
                {"Name": "PhoneNumber", "Value": phone},
            ]
        }
    return {"Body": {"stkCallback": callback}}


def paid_callback():
    return stk_callback(0, "Success", amount=50, phone=254712345678, receipt="RK12ABC")


class DarajaCallbackTests(TestCase):
    def setUp(self):
        self.provider = RecordingProvider()
        user = User.objects.create_user(email="buyer@example.test")
        product = Product.objects.create(code="boost", name="Boost", price_kes=50, kind="boost")
        self.purchase = create_purchase(
            user=user,
            product_code=product.code,
            phone="0712345678",
            idempotency_key=str(uuid.uuid4()),
            provider=self.provider,
        )

    def test_failure_reported_by_safaricom_is_recorded_without_a_query(self):
        with self.assertLogs("anonymoke.store", level="INFO") as logs:
            process_daraja_callback(
                payload=stk_callback(2001, "The initiator information is invalid."),
                provider=self.provider,
            )
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, Purchase.Status.FAILED)
        self.assertEqual(self.purchase.result_code, 2001)
        self.assertEqual(
            self.purchase.raw_callback["result_desc"], "The initiator information is invalid."
        )
        self.assertEqual(self.provider.queries, 0)
        self.assertTrue(any("result_code=2001" in line for line in logs.output))

    def test_timeout_keeps_purchase_pending(self):
        process_daraja_callback(
            payload=stk_callback(1037, "DS timeout user cannot be reached"),
            provider=self.provider,
        )
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, Purchase.Status.PENDING)
        self.assertEqual(self.purchase.result_code, 1037)

    def test_paid_boost_starts_at_once(self):
        self.provider.completed = True
        profile = Profile.objects.create(
            user=self.purchase.user,
            alias="buyer",
            age_years=27,
            gender="NB",
            cell=Point(36.82, -1.28, srid=4326),
            cell_updated_at=timezone.now(),
        )
        for kind in ("location", "sensitive_data"):
            ConsentRecord.objects.create(
                user=profile.user, consent_type=kind, version="test", granted=True
            )
        with self.assertLogs("anonymoke.store", level="INFO") as logs:
            process_daraja_callback(payload=paid_callback(), provider=self.provider)
            # Safaricom retries deliver the same callback; it must not start a second boost.
            process_daraja_callback(payload=paid_callback(), provider=self.provider)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, Purchase.Status.COMPLETED)
        boost = ProfileBoost.objects.get(profile=profile)
        self.assertEqual(boost.client_activation_id, self.purchase.id)
        self.assertGreater(boost.expires_at, timezone.now())
        self.assertEqual(Entitlement.objects.get(source_purchase=self.purchase).quantity, 0)
        self.assertEqual(sum("boost_auto_activated" in line for line in logs.output), 1)

    def test_paid_boost_waits_when_profile_cannot_be_boosted(self):
        # No profile location yet: keep the boost for the Boost screen to activate later.
        self.provider.completed = True
        Profile.objects.create(user=self.purchase.user, alias="buyer", age_years=27, gender="NB")
        with self.assertLogs("anonymoke.store", level="WARNING") as logs:
            process_daraja_callback(payload=paid_callback(), provider=self.provider)
        self.assertFalse(ProfileBoost.objects.exists())
        self.assertEqual(Entitlement.objects.get(source_purchase=self.purchase).quantity, 1)
        self.assertIn("boost_auto_activate_skipped", logs.output[0])

    def test_reported_success_is_still_verified_with_a_query(self):
        process_daraja_callback(payload=stk_callback(0, "Success"), provider=self.provider)
        self.assertEqual(self.provider.queries, 1)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, Purchase.Status.PENDING)


@override_settings(
    PAYMENT_PROVIDER="daraja",
    DARAJA_CONSUMER_KEY="k",
    DARAJA_CONSUMER_SECRET="s",
    DARAJA_SHORTCODE="123456",
    DARAJA_TILL_NUMBER="654321",
    DARAJA_PASSKEY="p",
    DARAJA_CALLBACK_BASE_URL="https://api.example.test",
    DARAJA_CALLBACK_TOKEN="t",
)
class DarajaHttpErrorTests(TestCase):
    def test_http_error_body_is_logged_and_distinguished_from_outage(self):
        error = urllib.error.HTTPError(
            "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
            500,
            "Server Error",
            {},
            io.BytesIO(
                b'{"errorCode":"500.001.1001","errorMessage":"The transaction is being processed"}'
            ),
        )
        provider = DarajaPaymentProvider()
        with (
            patch.object(provider, "_access_token", return_value="token"),
            patch("urllib.request.urlopen", side_effect=error),
            self.assertLogs("anonymoke.store", level="WARNING") as logs,
        ):
            with self.assertRaisesMessage(PaymentProviderError, "daraja_unavailable"):
                provider.query_transaction(checkout_request_id="ws_CO_1")
        self.assertIn("500.001.1001", logs.output[0])
