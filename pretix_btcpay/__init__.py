__version__ = "0.1.1"

try:
    from pretix.base.plugins import PluginType
except ImportError:
    PluginType = None


class PretixPluginMeta:
    name = "BTCPay Server"
    author = "Nathan Day"
    description = "Pay with Bitcoin (Lightning / on-chain) via BTCPay Server"
    visible = True
    version = __version__
    category = "PAYMENT"


if PluginType is not None:
    PretixPluginMeta.type = PluginType.PAYMENT