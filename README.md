# Ace Cricketer — Full-stack e-commerce MVP

A responsive storefront and working server-side shop implementation for **Ace Cricketer, Bengaluru**. Includes live database-backed inventory, persistent browser cart, guest checkout, Razorpay payment integration, webhook handling, customer order tracking, and a protected staff dashboard.

> **Status: Implementation / review build, NOT a live store.** The starter catalog consists entirely of illustrative products, stock figures and prices. They are not verified Ace Cricketer items. The official logo, photographs, contact details, delivery rates, policies and merchant identity need owner approval. No live payment can be accepted without Razorpay merchant credentials and configuration.

## Stack

- **Front end:** Responsive HTML5, CSS, vanilla JavaScript — no bundler, lightweight hosting.
- **API:** Python FastAPI + Pydantic.
- **Database:** SQLAlchemy 2 ORM; SQLite for local development, PostgreSQL with Docker Compose.
- **Payments:** Razorpay Orders API, Checkout.js, server-side HMAC verification, provider payment capture query, signed webhooks.
- **Security:** Server-authoritative pricing; atomic stock updates; reserved-stock expiry; admin password authentication with Argon2, signed HttpOnly SameSite cookies, CSRF header, origin checking, session expiration; generic API validation; no card storage.

## Fastest local preview

Requires Python 3.11 or newer.

```bash
cd ace-cricketer-commerce
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env: replace SESSION_SECRET and ADMIN_PASSWORD with strong unique values.
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Storefront: `http://127.0.0.1:8000`
- Staff dashboard: `http://127.0.0.1:8000/admin`
- Development API docs: `http://127.0.0.1:8000/api/docs`
- In demo mode, orders appear as **unpaid**; no external payment is requested.
- To test staff login, set `ADMIN_USERNAME` and a non-placeholder `ADMIN_PASSWORD` in `.env`.

### Docker + PostgreSQL

Add a unique `POSTGRES_PASSWORD` to `.env`, then:

```bash
docker compose up --build
```

The Compose file uses PostgreSQL. The host runs on port 8000; `SITE_ORIGIN` must match the **actual URL** used to access the site. For real traffic, terminate HTTPS on a proxy / load balancer. Do not expose PostgreSQL publicly.

## Features

| Customer | Shop owner / admin |
|---|---|
| Search, category filters and sorting | Login and session management |
| Mobile-friendly browse and product cards | Product create/edit, prices, SKU, visibility, stock |
| Local persistent cart with quantity controls | View orders and customer delivery details |
| Checkout validates Indian phone / PIN | Verify payment vs. fulfilment state separately |
| Server-calculated subtotal and shipping | Change fulfilment: new → processing → shipped → delivered |
| Razorpay checkout after server-side order creation | Stop unverified/unpaid orders from shipping |
| Track order by reference + checkout email | View captured revenue and low stock |

## Enable Razorpay **test** checkout

1. Obtain a Razorpay **test** key ID and secret from the authorized store merchant account.
2. Configure a Razorpay webhook endpoint: `https://YOUR_DOMAIN/api/webhooks/razorpay` and its independently generated webhook secret. Subscribe to `payment.captured`, `payment.failed`, and `order.paid`.
3. Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` in `.env`.
4. Set `DEMO_MODE=false` and import **verified** merchant products in the admin dashboard. Sample products are *hidden* from the live storefront until explicitly made real by the merchant (`sample=false`).
5. Start the service, test successful/cancelled/failed/late payments with a public test webhook URL, and verify order state, inventory and webhook retries.
6. Only after business verification, compliance checks and written owner approval should the merchant replace test keys with live keys. Use production HTTPS, correct domain and `APP_ENV=production`.

No payment keys are bundled. The browser receives the public key ID only; secrets remain server-side. The payment callback signature uses the **saved** gateway order ID, then fetches the payment to verify `captured` and correct amount/order. Signed webhooks also update the payment status. A late capture after stock-release is flagged `review`, not automatically fulfilled. Razorpay checkout script is hosted by Razorpay.

Official payment references:
- https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/
- https://razorpay.com/docs/webhooks/validate-test/

## Configuration

Set these in `.env`, never in public JavaScript or Git:

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` or `production` (production refuses demo mode and missing payment secrets) |
| `DEMO_MODE` | Seeds sample products; demo checkout records unpaid orders |
| `DATABASE_URL` | SQLite for local, PostgreSQL URL for deployment |
| `SESSION_SECRET` | Long unique signing key for staff sessions |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Staff login credentials; no functional default password |
| `SITE_ORIGIN` | Exact origin for admin write-origin verification |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Merchant gateway keys |
| `RAZORPAY_WEBHOOK_SECRET` | HMAC secret for the webhook endpoint; different from key secret |
| `SHIPPING_FEE_PAISE` | Flat delivery fee in paise, e.g. 7500 = ₹75 |
| `FREE_SHIPPING_ABOVE_PAISE` | Free shipping subtotal threshold; 0 disables threshold |
| `RESERVATION_MINUTES` | Cart inventory reservation expiration, default 30 minutes |

**Shipping is configured to ₹0 initially solely as a preview default, not a claim about Ace Cricketer delivery terms.** For real use, choose and disclose actual merchant delivery fees/tax treatment. Do not enable paid checkout until approved.

## Data and operations

- Purchases create pending orders with server-calculated item snapshots; quantity decrements atomically and is returned on failure, cancellation or reservation expiry. Expiry is reconciled when a new checkout or admin order-list request occurs; **production requires a scheduled expiration worker** so forgotten reservations are not held indefinitely.
- Customer tracking requires an unguessable order reference and the corresponding email, but production also requires ingress rate limits / bot defenses.
- Staff sessions last eight hours. In-process login throttling is a convenience only; put an edge-level rate limiter and audit logging in front of a production deployment.
- No email receipts, shipping-carrier integration, invoice/GST logic, exchanges/returns, refunds, customer accounts, file uploads or CRM sync are implemented.
- Schema creation uses SQLAlchemy `create_all` for onboarding; **use Alembic migrations before production**.
- Payment webhook delivery is signed and current order updates are idempotent; add a durable webhook event log / queue and reconciliation job before higher-volume launch.
- Implement observability (structured logs, alerting on webhook failures, payment/stock discrepancies), encrypted backups and tested restores, HTTPS and secret rotation.
- Define and publish legally adequate Privacy Policy, Shipping Policy, Terms and Refund/Return Policy, plus business information and contact channels, with the shop owner and legal adviser before going live.
- Check storefront copy, public directory address/phone and permission to use official brand identity. `acecricketer.com` is listed by third parties but was **not verified as an active domain**.

## Tests

```bash
pytest -q
```

Tests cover demo checkout, server-authoritative pricing, stock update, validation, reservation expiration, owner auth/CSRF, product editing, order cancellation, origin checking and HMAC signatures.

## File layout

```text
app/main.py         FastAPI routes, order lifecycle, admin routes
app/models.py       SQLAlchemy products/orders/order-items
app/schemas.py      Validated request contracts
app/payment.py      Razorpay API and HMAC validation
app/seed.py         Demo products; illustrative only
static/index.html   Storefront
static/admin.html   Owner dashboard
static/assets/      CSS, JS, original SVG equipment illustrations
Dockerfile          App container
docker-compose.yml  App + PostgreSQL for local/container staging
tests/              Automated backend checks
```
