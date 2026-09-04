import logging
from collections import OrderedDict

from django import forms
from django.template.loader import get_template
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from i18nfield.forms import I18nFormField, I18nTextInput
from i18nfield.strings import LazyI18nString

from pretix.base.forms import SecretKeySettingsField
from pretix.base.models import OrderPayment
from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.multidomain.urlreverse import build_absolute_uri, eventreverse

from .api import BTCPayAPI, BTCPayError, WEBHOOK_EVENTS

logger = logging.getLogger(__name__)


class BTCPayServer(BasePaymentProvider):
    identifier = "btcpay_greenfield"
    verbose_name = _("BTCPay Server (Bitcoin / Lightning)")
    execute_payment_needs_user = True
    abort_pending_allowed = True

    @property
    def public_name(self):
        return str(
            self.settings.get("public_name", as_type=LazyI18nString)
            or _("Bitcoin / Lightning Network")
        )

    @property
    def test_mode_message(self):
        if not self.settings.url or not self.settings.api_key or not self.settings.store_id:
            return _(
                "You have not yet configured your BTCPay Server URL, API key or "
                "store ID."
            )
        return None

    @cached_property
    def client(self) -> BTCPayAPI:
        return BTCPayAPI(
            url=str(self.settings.url),
            api_key=str(self.settings.api_key),
        )

    @property
    def webhook_url(self) -> str:
        return build_absolute_uri(self.event, "plugins:pretix_btcpay:webhook")

    def _ensure_webhook(self):
        """Create (or refresh) the store webhook and store its id and secret
        in the provider settings so incoming webhook events can be verified."""
        if self.settings.webhook_id and self.settings.webhook_secret:
            return
        store_id = str(self.settings.store_id)
        existing = None
        try:
            for wh in self.client.list_webhooks(store_id):
                if wh.get("url") == self.webhook_url:
                    existing = wh
                    break
        except BTCPayError:
            existing = None
        if existing:
            # Without the stored secret we cannot verify signatures, so
            # recreate the webhook to obtain a fresh secret.
            try:
                self.client.delete_webhook(store_id, existing["id"])
            except BTCPayError:
                logger.exception("BTCPay: could not delete stale webhook")
        try:
            result = self.client.create_webhook(
                store_id,
                url=self.webhook_url,
                events=WEBHOOK_EVENTS,
            )
        except BTCPayError:
            logger.exception("BTCPay: could not register webhook")
            raise
        self.settings.set("webhook_id", result.get("id", ""))
        self.settings.set("webhook_secret", result.get("secret", ""))

    @property
    def settings_form_fields(self):
        d = OrderedDict(
            [
                (
                    "url",
                    forms.URLField(
                        label=_("BTCPay Server URL"),
                        help_text=_(
                            "The base URL of your BTCPay Server instance, e.g. "
                            "https://btcpay.example.com"
                        ),
                    ),
                ),
                (
                    "api_key",
                    SecretKeySettingsField(
                        label=_("BTCPay Server API key"),
                        help_text=_(
                            "An API key with the permissions "
                            "btcpay.store.cancreateinvoice, "
                            "btcpay.store.canviewinvoices and "
                            "btcpay.store.webhooks.canmodifywebhooks, limited "
                            "to the store receiving the payments."
                        ),
                    ),
                ),
                (
                    "store_id",
                    forms.CharField(
                        label=_("Store ID"),
                        help_text=_(
                            "The ID of the BTCPay Server store that should "
                            "receive the payments (shown in the store's "
                            "settings page or in the store URL)."
                        ),
                    ),
                ),
                (
                    "expiry",
                    forms.IntegerField(
                        label=_("Payment link expiry (minutes)"),
                        min_value=1,
                        initial=30,
                    ),
                ),
                (
                    "public_name",
                    I18nFormField(
                        label=_("Payment method name"),
                        widget=I18nTextInput,
                        help_text=_(
                            "The name of the payment method that is shown to "
                            "your customers during checkout."
                        ),
                    ),
                ),
            ]
            + list(super().settings_form_fields.items())
        )
        d.move_to_end("public_name", last=False)
        d.move_to_end("_enabled", last=False)
        return d

    def settings_content_render(self, request) -> str:
        parts = [
            '<p>{}</p>'.format(_(
                "To accept payments, you need a BTCPay Server instance with a "
                "store that has a wallet configured."
            )),
            '<p><b>{}</b></p>'.format(_("You will need:")),
            '<ul>',
        ]
        parts.append(
            '<li>{}</li>'.format(_(
                "The base URL of your BTCPay Server instance"
            ))
        )
        parts.append(
            '<li>{}</li>'.format(_(
                "An API key restricted to the receiving store with the "
                "permissions btcpay.store.cancreateinvoice, "
                "btcpay.store.canviewinvoices and "
                "btcpay.store.webhooks.canmodifywebhooks"
            ))
        )
        parts.append(
            '<li>{}</li>'.format(_(
                "The store ID of the receiving store (can be found in the "
                "store's settings)"
            ))
        )
        parts.append('</ul>')
        if self.settings.url and self.settings.api_key and self.settings.store_id:
            parts.append(
                '<p>{}</p>'.format(_(
                    "The webhook endpoint for this event will be registered "
                    "automatically on your store's webhooks. It will be:"
                ))
            )
            parts.append('<p><code>{}</code></p>'.format(self.webhook_url))
        return "".join(parts)

    def payment_form_render(self, request) -> str:
        template = get_template("pretix_btcpay/checkout_payment_form.html")
        ctx = {"request": request, "event": self.event, "settings": self.settings}
        return template.render(ctx)

    def checkout_confirm_render(self, request, order=None, info_data=None) -> str:
        template = get_template("pretix_btcpay/checkout_payment_confirm.html")
        ctx = {"request": request, "event": self.event, "order": order}
        return template.render(ctx)

    def payment_is_valid_session(self, request) -> bool:
        return True

    def checkout_prepare(self, request, cart) -> bool:
        return True

    def _invoice(self, payment: OrderPayment):
        """
        Return the invoice id currently stored on the payment, creating a new
        BTCPay invoice (and registering the store webhook if needed) on demand
        when none exists yet.

        pretix sends the order-placed (and payment reminder) emails before it
        calls ``execute_payment``, so at email render time the payment has not
        had an invoice created for it yet. Creating it lazily here guarantees
        the payment link embedded in those emails is always valid instead of
        degrading to a broken ``/i/None`` URL.
        """
        invoice_id = payment.info_data.get("invoice_id")
        if invoice_id:
            return invoice_id
        return self._create_invoice(payment)

    def _create_invoice(self, payment: OrderPayment):
        order_url = eventreverse(
            self.event,
            "presale:event.order",
            kwargs={
                "order": payment.order.code,
                "secret": payment.order.secret,
            },
        )
        self._ensure_webhook()
        invoice = self.client.create_invoice(
            str(self.settings.store_id),
            amount=str(payment.amount),
            currency=str(self.event.currency),
            order_id=payment.order.code,
            metadata={"pretixPaymentId": payment.pk},
            redirect_url=order_url,
            expiry_minutes=int(self.settings.get("expiry", as_type=int) or 30),
        )
        payment.info_data = {
            "invoice_id": invoice["id"],
            "checkout_link": invoice.get("checkoutLink", ""),
        }
        payment.save(update_fields=["info"])
        payment.order.log_action(
            "pretix_btcpay.invoice.created",
            data={"invoice_id": invoice["id"]},
        )
        return invoice["id"]

    def execute_payment(self, request, payment: OrderPayment):
        try:
            invoice_id = self._invoice(payment)
        except BTCPayError:
            logger.exception("BTCPay: could not create invoice")
            raise PaymentException(
                _(
                    "We had trouble creating your payment. Please try again "
                    "and get in touch with us if this problem persists."
                )
            )
        return self.client.url + "/i/" + invoice_id

    def payment_pending_render(self, request, payment: OrderPayment) -> str:
        template = get_template("pretix_btcpay/pending.html")
        ctx = {
            "request": request,
            "event": self.event,
            "settings": self.settings,
            "order": payment.order,
            "payment": payment,
            "status_url": eventreverse(
                self.event,
                "plugins:pretix_btcpay:status",
                kwargs={
                    "order": payment.order.code,
                    "payment": payment.pk,
                },
            ),
        }
        if payment.state in (
            OrderPayment.PAYMENT_STATE_CREATED,
            OrderPayment.PAYMENT_STATE_PENDING,
        ):
            try:
                invoice_id = self._invoice(payment)
            except BTCPayError:
                invoice_id = payment.info_data.get("invoice_id")
            ctx["checkout_link"] = (
                payment.info_data.get("checkout_link")
                or (self.client.url + "/i/" + invoice_id if invoice_id else None)
            )
        else:
            ctx["checkout_link"] = None
        return template.render(ctx)

    def order_pending_mail_render(self, order, payment: OrderPayment) -> str:
        try:
            invoice_id = self._invoice(payment)
        except BTCPayError:
            invoice_id = payment.info_data.get("invoice_id")
        checkout_link = payment.info_data.get("checkout_link")
        if not checkout_link and invoice_id:
            checkout_link = self.client.url + "/i/" + invoice_id
        if not checkout_link:
            return _(
                "Your Bitcoin / Lightning payment is still being prepared. "
                "Please return to your order and choose how to pay."
            )
        return _("To pay for your order, please visit the following page: {url}").format(
            url=checkout_link
        )

    def payment_control_render(self, request, payment: OrderPayment) -> str:
        template = get_template("pretix_btcpay/control.html")
        invoice_id = payment.info_data.get("invoice_id")
        status = {}
        if invoice_id:
            try:
                status = self.client.get_invoice(
                    str(self.settings.store_id), invoice_id
                )
            except Exception:
                status = {}
        ctx = {
            "request": request,
            "event": self.event,
            "payment": payment,
            "invoice_id": invoice_id,
            "status": status,
        }
        return template.render(ctx)

    def payment_control_render_short(self, payment: OrderPayment) -> str:
        invoice_id = payment.info_data.get("invoice_id")
        return "#" + invoice_id if invoice_id else self.verbose_name

    def payment_presale_render(self, payment: OrderPayment) -> str:
        return "BTCPay Server"

    def matching_id(self, payment: OrderPayment) -> str:
        return payment.info_data.get("invoice_id")

    def api_payment_details(self, payment: OrderPayment) -> dict:
        return {
            "invoice_id": payment.info_data.get("invoice_id"),
        }

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        return False

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return False

    def shred_payment_info(self, obj):
        info = obj.info_data
        info["invoice_id"] = "█" if info.get("invoice_id") else ""
        obj.info_data = info
        obj.save(update_fields=["info"])