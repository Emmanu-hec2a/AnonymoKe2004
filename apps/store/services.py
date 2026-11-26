import hashlib
import hmac
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.crypto import decrypt_text, encrypt_text

from .models import Entitlement, FinancialTransaction, PaymentCallbackLog, Product, Purchase
from .providers import BasePaymentProvider, default_payment_provider

logger = logging.getLogger("anonymoke.store")
KENYAN_PHONE_RE = re.compile(r"^(?:254|0)(?:7|1)\d{8}$")


def normalize_kenyan_phone(value: str) -> str:
    compact = re.sub(r"[\s+()-]", "", value.strip())
    if compact.startswith("0"):
        compact = f"254{compact[1:]}"
    if not KENYAN_PHONE_RE.fullmatch(compact):
        raise ValueError("invalid_kenyan_phone")
    return compact


def _phone_hash(phone: str) -> str:
    return hmac.new(settings.JWT_SECRET.encode(), phone.encode(), hashlib.sha256).hexdigest()


def _redact_callback(payload: dict) -> dict:
    """Keep reconciliation fields while avoiding provider phone/PII persistence."""
    result = payload.get("Body", {}).get("stkCallback", {}) if isinstance(payload, dict) else {}
    return {
        "checkout_request_id": result.get("CheckoutRequestID"),
        "merchant_request_id": result.get("MerchantRequestID"),
        "result_code": result.get("ResultCode"),
        "result_desc": str(result.get("ResultDesc", ""))[:500],
    }


def _callback_details(payload: dict) -> dict:
    result = payload.get("Body", {}).get("stkCallback", {}) if isinstance(payload, dict) else {}
    metadata = result.get("CallbackMetadata", {}).get("Item", [])
    details = {}
    for item in metadata if isinstance(metadata, list) else []:
        if isinstance(item, dict) and item.get("Name"):
            details[item["Name"]] = item.get("Value")
    return details


def _provider(provider: BasePaymentProvider | None) -> BasePaymentProvider:
    return provider or default_payment_provider()


@transaction.atomic
def create_purchase(*, user, product_code: str, phone: str, idempotency_key: str, provider=None):
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValueError("idempotency_key_required")
    existing = Purchase.objects.filter(user=user, idempotency_key=idempotency_key).first()
    if existing:
        return existing
    product = Product.objects.filter(code=product_code, is_active=True).first()
    if not product:
        raise ValueError("product_not_found")
    normalized = normalize_kenyan_phone(phone)
    purchase = Purchase.objects.create(
        user=user,
        product=product,
        amount_kes=product.price_kes,
        phone_hash=_phone_hash(normalized),
        phone_ciphertext=encrypt_text(normalized),
        idempotency_key=idempotency_key,
    )
    try:
        initiated = _provider(provider).initiate_stk(
            phone=normalized, amount_kes=product.price_kes, account_reference=str(purchase.id)
        )
    except Exception:
        purchase.status = Purchase.Status.FAILED
        purchase.save(update_fields=["status", "updated_at"])
        raise
    purchase.checkout_request_id = initiated.checkout_request_id
    purchase.merchant_request_id = initiated.merchant_request_id
    purchase.save(update_fields=["checkout_request_id", "merchant_request_id", "updated_at"])
    return purchase


@transaction.atomic
def process_daraja_callback(*, payload: dict, provider=None) -> Purchase | None:
    callback = payload.get("Body", {}).get("stkCallback", {}) if isinstance(payload, dict) else {}
    checkout_id = callback.get("CheckoutRequestID")
    if not checkout_id:
        raise ValueError("callback_missing_checkout_request_id")
    log, _ = PaymentCallbackLog.objects.update_or_create(
        checkout_request_id=checkout_id,
        defaults={"payload": _redact_callback(payload)},
    )
    purchase = Purchase.objects.select_for_update().filter(checkout_request_id=checkout_id).first()
    if not purchase:
        log.processed_at = timezone.now()
        log.save(update_fields=["processed_at"])
        return None
    if purchase.status != Purchase.Status.PENDING:
        log.processed_at = timezone.now()
        log.save(update_fields=["processed_at"])
        return purchase
    purchase.raw_callback = _redact_callback(payload)
    try:
        callback_code = int(callback.get("ResultCode"))
    except (TypeError, ValueError):
        callback_code = None
    logger.info(
        "daraja_callback checkout=%s purchase=%s result_code=%s result_desc=%s",
        checkout_id,
        purchase.pk,
        callback_code,
        purchase.raw_callback["result_desc"],
    )
    if callback_code not in (None, 0):
        # Safaricom reported a failure (cancelled, timed out, wrong credentials, ...).
        # Nothing to verify: record it. 1037 is a timeout the user may still answer.
        purchase.result_code = callback_code
        if callback_code != 1037:
            purchase.status = Purchase.Status.FAILED
        purchase.save(update_fields=["result_code", "raw_callback", "status", "updated_at"])
        log.processed_at = timezone.now()
        log.save(update_fields=["processed_at"])
        return purchase
    # A reported success is confirmed with Safaricom before anything is granted.
    query = _provider(provider).query_transaction(checkout_request_id=checkout_id)
    purchase.result_code = query.result_code
    if not query.completed:
        if query.result_code is not None and query.result_code != 1037:
            purchase.status = Purchase.Status.FAILED
        purchase.save(update_fields=["result_code", "raw_callback", "status", "updated_at"])
        log.processed_at = timezone.now()
        log.save(update_fields=["processed_at"])
        return purchase

    details = _callback_details(payload)
    try:
        callback_amount = int(details["Amount"])
        callback_phone = normalize_kenyan_phone(str(details["PhoneNumber"]))
        receipt = str(details["MpesaReceiptNumber"])
        stored_phone = decrypt_text(bytes(purchase.phone_ciphertext))
    except (KeyError, TypeError, ValueError):
        callback_amount = None
        callback_phone = None
        receipt = None
        stored_phone = None
    if (
        purchase.user_id is None
        or callback_amount != purchase.amount_kes
        or not receipt
        or not stored_phone
        or callback_phone != stored_phone
    ):
        logger.warning(
            "daraja_callback_mismatch purchase=%s amount_ok=%s receipt=%s phone_ok=%s",
            purchase.pk,
            callback_amount == purchase.amount_kes,
            bool(receipt),
            bool(stored_phone) and callback_phone == stored_phone,
        )
        purchase.status = Purchase.Status.FAILED
        purchase.save(update_fields=["result_code", "raw_callback", "status", "updated_at"])
        log.processed_at = timezone.now()
        log.save(update_fields=["processed_at"])
        return purchase

    purchase.status = Purchase.Status.COMPLETED
    purchase.mpesa_receipt = receipt
    purchase.completed_at = timezone.now()
    purchase.save(
        update_fields=[
            "result_code",
            "raw_callback",
            "status",
            "mpesa_receipt",
            "completed_at",
            "updated_at",
        ]
    )
    FinancialTransaction.objects.get_or_create(
        provider="daraja",
        provider_reference=receipt,
        defaults={
            "user": purchase.user,
            "account_reference_hash": _phone_hash(str(purchase.id)),
            "amount_kes": purchase.amount_kes,
            "retained_until": timezone.now() + timedelta(days=365 * 7),
        },
    )
    _grant_entitlement(purchase)
    log.processed_at = timezone.now()
    log.save(update_fields=["processed_at"])
    return purchase


def _grant_entitlement(purchase: Purchase) -> Entitlement:
    entitlement, created = Entitlement.objects.get_or_create(
        user=purchase.user,
        source_purchase=purchase,
        kind=purchase.product.kind,
        defaults={
            "quantity": 1,
            "expires_at": (
                timezone.now() + timedelta(days=purchase.product.duration_days)
                if purchase.product.duration_days
                else None
            ),
        },
    )
    if not created:
        return entitlement
    return entitlement
