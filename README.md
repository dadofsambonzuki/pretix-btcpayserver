# pretix BTCPay Server

Accept Bitcoin Lightning and on-chain Bitcoin payments in [pretix](https://pretix.eu/) using the [BTCPay Server](https://btcpayserver.org/) **Greenfield API** (not the deprecated BitPay-compatible API).

The customer pays on the BTCPay checkout page hosted by your BTCPay Server instance. A store-level webhook with signature verification and a small polling script in the pending-payment page keep pretix in sync with the payment status.

## Requirements

- **pretix** ≥ 4.0 (Django-based event management platform)
- **Python** ≥ 3.11
- **BTCPay Server** instance with a store configured (with a wallet)
- Django ≥ 4, requests, i18nfield

## Installation

```bash
# Install from source
pip install -e .
```

Then activate the plugin in the pretix "Plugins" settings page. You can also enable the plugin per event.

## Configuration

In the event's **Settings → Payment → BTCPay Server (Bitcoin / Lightning)** you need to provide:

| Setting | Description |
|---|---|
| **BTCPay Server URL** | The base URL of your BTCPay Server instance, e.g. `https://btcpay.example.com` |
| **API key** | An API key restricted to the receiving store with permissions: `btcpay.store.cancreateinvoice`, `btcpay.store.canviewinvoices`, `btcpay.store.webhooks.canmodifywebhooks` |
| **Store ID** | The ID of the store that will receive the payments (shown in the store's settings page or in the store URL) |
| **Payment link expiry** | How many minutes before the payment link expires (default: 30) |
| **Payment method name** | Custom name shown to customers during checkout |

### Webhook

The webhook endpoint is registered automatically on your store when the first payment is created. It uses HMAC-SHA256 signature verification to ensure authenticity.

Endpoints:
- `https://yourpretix.example.com/{event}/btcpay/webhook/` — receives invoice status updates from BTCPay Server
- `https://yourpretix.example.com/{event}/btcpay/status/{order}/{payment}/` — polling endpoint for the pending payment page

## How it works

1. Customer selects "Bitcoin / Lightning Network" during checkout
2. An invoice is created on your BTCPay Server via the Greenfield API
3. Customer is redirected to the BTCPay checkout page
4. BTCPay Server sends webhook events (`InvoiceSettled`, `InvoiceExpired`, etc.) to pretix
5. The webhook handler verifies the signature and confirms the payment
6. While the payment is pending, the order page polls for status updates
7. On successful payment, the order is confirmed; on expiry, the payment is marked as failed

## Supported webhook events

- `InvoiceSettled`
- `InvoiceProcessing`
- `InvoiceExpired`
- `InvoiceInvalid`
- `InvoiceReceivedPayment`
- `InvoicePaymentSettled`

## Development

```bash
# Clone the repo
git clone https://github.com/dadofsambonzuki/pretix-btcpayserver
cd pretix-btcpayserver

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e .
```

## License

MIT