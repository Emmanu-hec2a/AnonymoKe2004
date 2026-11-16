import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.conf import settings


@dataclass(frozen=True)
class CheckoutInitiation:
    checkout_request_id: str
    merchant_request_id: str


@dataclass(frozen=True)
class TransactionQuery:
    completed: bool
    result_code: int | None
    raw: dict


class PaymentProviderError(RuntimeError):
    pass


class BasePaymentProvider:
    def initiate_stk(
        self, *, phone: str, amount_kes: int, account_reference: str
    ) -> CheckoutInitiation:
        raise NotImplementedError

    def query_transaction(self, *, checkout_request_id: str) -> TransactionQuery:
        raise NotImplementedError


class DummyPaymentProvider(BasePaymentProvider):
    def initiate_stk(self, *, phone: str, amount_kes: int, account_reference: str):  # noqa: ARG002
        token = account_reference.replace("-", "")
        return CheckoutInitiation(
            checkout_request_id=f"dummy-{token}", merchant_request_id=f"dummy-{token}"
        )

    def query_transaction(self, *, checkout_request_id: str):  # noqa: ARG002
        return TransactionQuery(
            completed=False,
            result_code=None,
            raw={"provider": "dummy", "status": "pending"},
        )


class DarajaPaymentProvider(BasePaymentProvider):
    def __init__(self):
        required = (
            settings.DARAJA_CONSUMER_KEY,
            settings.DARAJA_CONSUMER_SECRET,
            settings.DARAJA_SHORTCODE,
            settings.DARAJA_TILL_NUMBER,
            settings.DARAJA_PASSKEY,
            settings.DARAJA_CALLBACK_BASE_URL,
        )
        if not all(required):
            raise PaymentProviderError("daraja_not_configured")
        self.base_url = settings.DARAJA_BASE_URL.rstrip("/")

    def _request(self, url: str, *, method: str = "GET", body: bytes | None = None, headers=None):
        request = urllib.request.Request(  # noqa: S310 - URL is configured by the operator
            url, data=body, method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise PaymentProviderError("daraja_unavailable") from exc

    def _access_token(self) -> str:
        credentials = base64.b64encode(
            f"{settings.DARAJA_CONSUMER_KEY}:{settings.DARAJA_CONSUMER_SECRET}".encode()
        ).decode()
        payload = self._request(
            f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials",
            headers={"Authorization": f"Basic {credentials}"},
        )
        token = payload.get("access_token")
        if not token:
            raise PaymentProviderError("daraja_auth_failed")
        return token

    def _timestamp(self) -> str:
        return datetime.now(UTC).astimezone(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")

    def _password(self, timestamp: str) -> str:
        raw = f"{settings.DARAJA_SHORTCODE}{settings.DARAJA_PASSKEY}{timestamp}"
        return base64.b64encode(raw.encode()).decode()

    def initiate_stk(self, *, phone: str, amount_kes: int, account_reference: str):
        timestamp = self._timestamp()
        payload = {
            "BusinessShortCode": settings.DARAJA_SHORTCODE,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            "TransactionType": "CustomerBuyGoodsOnline",
            "Amount": amount_kes,
            "PartyA": phone,
            "PartyB": settings.DARAJA_TILL_NUMBER,
            "PhoneNumber": phone,
            "CallBackURL": (
                f"{settings.DARAJA_CALLBACK_BASE_URL.rstrip('/')}/api/v1/payments/daraja/"
                f"callback/{settings.DARAJA_CALLBACK_TOKEN}/"
            ),
            "AccountReference": account_reference[:12],
            "TransactionDesc": "AnonymoKE purchase",
        }
        response = self._request(
            f"{self.base_url}/mpesa/stkpush/v1/processrequest",
            method="POST",
            body=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json",
            },
        )
        try:
            return CheckoutInitiation(
                checkout_request_id=response["CheckoutRequestID"],
                merchant_request_id=response["MerchantRequestID"],
            )
        except KeyError as exc:
            raise PaymentProviderError("daraja_invalid_initiation") from exc

    def query_transaction(self, *, checkout_request_id: str):
        timestamp = self._timestamp()
        payload = {
            "BusinessShortCode": settings.DARAJA_SHORTCODE,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }
        response = self._request(
            f"{self.base_url}/mpesa/stkpushquery/v1/query",
            method="POST",
            body=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json",
            },
        )
        result_code = response.get("ResultCode")
        try:
            result_code = int(result_code) if result_code is not None else None
        except (TypeError, ValueError):
            result_code = None
        return TransactionQuery(
            completed=result_code == 0,
            result_code=result_code,
            raw=response,
        )


def default_payment_provider() -> BasePaymentProvider:
    if settings.PAYMENT_PROVIDER == "daraja":
        return DarajaPaymentProvider()
    return DummyPaymentProvider()
