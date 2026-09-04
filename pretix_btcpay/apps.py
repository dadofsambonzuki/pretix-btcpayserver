from django.apps import AppConfig


class PluginConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pretix_btcpay"

    class PretixPluginMeta:
        name = "pretix BTCPay Server"
        author = "Nathan Day"
        description = "Pay with Bitcoin (Lightning / on-chain) via BTCPay Server (Greenfield API)"
        visible = True
        version = "0.1.0"
        category = "PAYMENT"

    def ready(self):
        from . import signals  # noqa: F401