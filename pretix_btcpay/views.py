import json
import logging

from django.db import transaction
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotFound,
    JsonResponse,
)
from django.views.decorators.csrf import csrf_exempt

from pretix.base.models import OrderPayment, Quota
from pretix.base.services.locking import LockTimeoutException

from .payment import BTCPayServer

logger = logging.getLogger(__name__)


@csrf_exempt
def webhook(request, *args, **kwargs):
    raw_body = request.body
    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError):
        return HttpResponseBadRequest("Invalid JSON payload")

    event_type = payload.get("type")
    invoice_id = payload.get("invoiceId")
    metadata = payload.get("metadata") or {}

    prov = BTCPayServer(request.event)
    secret = str(prov.settings.get("webhook_secret") or "")
    if not secret:
        logger.error("BTCPay: webhook received but no secret configured")
        return HttpResponse("Unavailable", status=503)

    sig_header = request.META.get("HTTP_BTCPAY_SIG")
    if not prov.client.verify_signature(secret, raw_body, sig_header):
        return HttpResponseBadRequest("Signature mismatch")

    request.event.log_action("pretix_btcpay.webhook", data=payload)

    order_code = metadata.get("orderId")
    payment_id = metadata.get("pretixPaymentId")
    if not order_code or not payment_id or not invoice_id:
        return HttpResponse(status=200)

    try:
        order = request.event.orders.get(code=order_code)
    except Exception:
        return HttpResponseNotFound("Order not found")

    try:
        payment_id = int(payment_id)
    except (TypeError, ValueError):
        return HttpResponseNotFound("Payment not found")

    payment = order.payments.get(pk=payment_id, provider="btcpay_greenfield")

    if payment.info_data.get("invoice_id") != invoice_id:
        return HttpResponseBadRequest("Invoice does not match payment")

    if event_type != "InvoiceSettled":
        return HttpResponse(status=200)

    if payment.state not in (
        OrderPayment.PAYMENT_STATE_CREATED,
        OrderPayment.PAYMENT_STATE_PENDING,
    ):
        return HttpResponse(status=200)

    with transaction.atomic():
        payment.refresh_from_db()
        if payment.state in (
            OrderPayment.PAYMENT_STATE_CREATED,
            OrderPayment.PAYMENT_STATE_PENDING,
        ):
            try:
                payment.confirm()
            except LockTimeoutException:
                return HttpResponse("Lock timeout, please try again.", status=503)
            except Quota.QuotaExceededException:
                return HttpResponse("Quota exceeded.", status=200)
    return HttpResponse(status=200)


def status(request, *args, **kwargs):
    order_code = kwargs.get("order")
    payment_id = kwargs.get("payment")
    if not (order_code and payment_id):
        return HttpResponseBadRequest("Missing parameters")

    try:
        order = request.event.orders.get(code=order_code)
    except Exception:
        return HttpResponseNotFound("Order not found")

    try:
        payment = order.payments.get(pk=payment_id, provider="btcpay_greenfield")
    except Exception:
        return HttpResponseNotFound("Payment not found")

    invoice_id = payment.info_data.get("invoice_id")
    if not invoice_id:
        return JsonResponse({"paid": False})

    prov = BTCPayServer(request.event)
    try:
        invoice = prov.client.get_invoice(str(prov.settings.store_id), invoice_id)
    except Exception:
        logger.exception("BTCPay: invoice status lookup failed")
        return HttpResponse("Unavailable", status=503)

    return JsonResponse({"paid": invoice.get("status") == "Settled"})