from django.urls import include, path

from pretix.multidomain import event_url

from .views import status, webhook

event_patterns = [
    path(
        "btcpay/",
        include(
            [
                path(
                    "webhook/",
                    event_url(webhook, name="webhook", require_live=False),
                ),
                path(
                    "status/<str:order>/<str:payment>/",
                    event_url(status, name="status", require_live=False),
                ),
            ]
        ),
    ),
]