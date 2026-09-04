from pretix.multidomain import event_url

from .views import status, webhook

event_patterns = [
    event_url(
        r"^btcpay/webhook/$",
        webhook,
        name="webhook",
        require_live=False,
    ),
    event_url(
        r"^btcpay/status/(?P<order>[^/]+)/(?P<payment>[^/]+)/$",
        status,
        name="status",
        require_live=False,
    ),
]