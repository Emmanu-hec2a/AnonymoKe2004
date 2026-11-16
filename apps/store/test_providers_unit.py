"""Buy Goods provider contract tests; no database or Django app setup required."""

import base64
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from .providers import DarajaPaymentProvider, PaymentProviderError

DARAJA_SETTINGS = {
    "DARAJA_BASE_URL": "https://sandbox.safaricom.co.ke",
    "DARAJA_CONSUMER_KEY": "test-consumer",
    "DARAJA_CONSUMER_SECRET": "test-secret",
    "DARAJA_SHORTCODE": "123456",
    "DARAJA_TILL_NUMBER": "654321",
    "DARAJA_PASSKEY": "test-passkey",
    "DARAJA_CALLBACK_BASE_URL": "https://api.example.test/",
    "DARAJA_CALLBACK_TOKEN": "test-callback-token",
}
TIMESTAMP = "20260102123456"


class BuyGoodsPaymentProviderTests(TestCase):
    def setUp(self):
        self.config = SimpleNamespace(**DARAJA_SETTINGS)
        self.enterContext(patch("apps.store.providers.settings", self.config))
        self.provider = DarajaPaymentProvider()
        self.enterContext(patch.object(self.provider, "_timestamp", return_value=TIMESTAMP))

    def expected_password(self):
        raw = f"{self.config.DARAJA_SHORTCODE}{self.config.DARAJA_PASSKEY}{TIMESTAMP}"
        return base64.b64encode(raw.encode()).decode()

    def test_stk_push_collects_to_till_and_authenticates_with_store_shortcode(self):
        with patch.object(
            self.provider,
            "_request",
            side_effect=[
                {"access_token": "test-token"},
                {"CheckoutRequestID": "checkout-123", "MerchantRequestID": "merchant-123"},
            ],
        ) as request:
            result = self.provider.initiate_stk(
                phone="254712345678", amount_kes=150, account_reference="purchase-12345678"
            )

        self.assertEqual(request.call_count, 2)
        call = request.call_args
        self.assertEqual(
            call.args[0], "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
        )
        self.assertEqual(call.kwargs["method"], "POST")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-token")
        payload = json.loads(call.kwargs["body"])
        self.assertEqual(payload["TransactionType"], "CustomerBuyGoodsOnline")
        self.assertEqual(payload["BusinessShortCode"], "123456")
        self.assertEqual(payload["PartyB"], "654321")
        self.assertEqual(payload["Password"], self.expected_password())
        self.assertEqual(payload["Timestamp"], TIMESTAMP)
        self.assertEqual(payload["Amount"], 150)
        self.assertEqual(payload["PartyA"], "254712345678")
        self.assertEqual(payload["PhoneNumber"], "254712345678")
        self.assertEqual(payload["AccountReference"], "purchase-123")
        self.assertEqual(
            payload["CallBackURL"],
            "https://api.example.test/api/v1/payments/daraja/callback/test-callback-token/",
        )
        self.assertEqual(result.checkout_request_id, "checkout-123")
        self.assertEqual(result.merchant_request_id, "merchant-123")

    def test_query_uses_store_shortcode_and_password_after_till_checkout(self):
        with patch.object(
            self.provider,
            "_request",
            side_effect=[{"access_token": "test-token"}, {"ResultCode": "0"}],
        ) as request:
            result = self.provider.query_transaction(checkout_request_id="checkout-123")

        self.assertEqual(request.call_count, 2)
        call = request.call_args
        self.assertEqual(
            call.args[0], "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query"
        )
        self.assertEqual(
            json.loads(call.kwargs["body"]),
            {
                "BusinessShortCode": "123456",
                "Password": self.expected_password(),
                "Timestamp": TIMESTAMP,
                "CheckoutRequestID": "checkout-123",
            },
        )
        self.assertTrue(result.completed)
        self.assertEqual(result.result_code, 0)

    def test_missing_till_is_rejected_instead_of_using_store_shortcode(self):
        self.config.DARAJA_TILL_NUMBER = ""
        with self.assertRaisesRegex(PaymentProviderError, "daraja_not_configured"):
            DarajaPaymentProvider()
