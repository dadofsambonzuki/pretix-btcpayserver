from pretix.base.plugins import PluginConfig


class BTCPayAppConfig(PluginConfig):
    name = "pretix_btcpay"
    verbose_name = "BTCPay Server"
    default = True

    class PretixPluginMeta:
        name = "BTCPay Server"
        author = "Nathan Day"
        description = "Pay with Bitcoin (Lightning / on-chain) via BTCPay Server"
        visible = True
        version = "0.1.0"
        category = "PAYMENT"

    def ready(self):
        from . import signals  # noqa: F401