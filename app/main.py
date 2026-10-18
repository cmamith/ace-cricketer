"""Ace Cricketer shop API (FastAPI + SQLAlchemy + Razorpay).

Production launch requires merchant approval, real catalog, policies, infrastructure
and end-to-end payment testing. See README.md.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any

from argon2 import PasswordHasher
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from .models import Base, Order, OrderItem, Product, utc_now
from .payment import PaymentProviderError, RazorpayGateway
from .schemas import (
    AdminLogin, AdminProduct, CheckoutRequest, FulfillmentUpdate, PaymentVerification, OrderTracking,
)
from .seed import seed_samples

load_dotenv()
LOG = logging.getLogger("ace_cricketer")
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
ph = PasswordHasher()


def as_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "on"}


def product_dict(p: Product) -> dict[str, Any]:
    return {key: getattr(p, key) for key in (
        "id", "sku", "name", "category", "description", "price_paise", "compare_at_paise",
        "stock", "image_url", "featured", "active", "sample"
    )}


def order_dict(order: Order, full: bool = False) -> dict[str, Any]:
    result = {
        "reference": order.reference,
        "customer_name": order.customer_name,
        "email": order.email,
        "total_paise": order.total_paise,
        "subtotal_paise": order.subtotal_paise,
        "shipping_paise": order.shipping_paise,
        "payment_status": order.payment_status,
        "fulfillment_status": order.fulfillment_status,
        "created_at": order.created_at.isoformat() + "Z",
        "items": [{"product_name": i.product_name, "product_sku": i.product_sku,
                   "quantity": i.quantity, "unit_paise": i.unit_paise} for i in order.items],
    }
    if full:
        result.update({
            "phone": order.phone, "address": order.address, "city": order.city,
            "state": order.state, "pincode": order.pincode, "notes": order.notes,
            "razorpay_order_id": order.razorpay_order_id, "razorpay_payment_id": order.razorpay_payment_id,
        })
    return result


def release_stock(db: Session, order: Order, new_payment_status: str) -> None:
    """Idempotently return reserved units for an unpaid order."""
    if order.payment_status != "pending":
        return
    for item in order.items:
        db.execute(update(Product).where(Product.id == item.product_id).values(stock=Product.stock + item.quantity))
    order.payment_status = new_payment_status


def expire_reservations(db: Session) -> None:
    expired = db.scalars(
        select(Order).where(Order.payment_status == "pending", Order.expires_at < utc_now())
        .options(selectinload(Order.items))
    ).all()
    for order in expired:
        release_stock(db, order, "expired")
    if expired:
        db.commit()
        LOG.info("Released %s expired checkout reservations", len(expired))


def mark_captured(order: Order, payment_id: str) -> None:
    # A late payment cannot silently move an expired order into fulfilment.
    if order.payment_status in {"expired", "failed"}:
        order.payment_status = "review"
    elif order.payment_status == "pending":
        order.payment_status = "captured"
    if payment_id:
        order.razorpay_payment_id = payment_id


def create_app(database_url: str | None = None, demo_mode: bool | None = None) -> FastAPI:
    env = os.getenv("APP_ENV", "development").lower()
    demo = as_bool(os.getenv("DEMO_MODE", "true")) if demo_mode is None else demo_mode
    if env == "production" and demo:
        raise RuntimeError("DEMO_MODE must be false in production")
    secret = os.getenv("SESSION_SECRET", "local-development-change-this")
    if env == "production" and (len(secret) < 32 or secret.startswith("replace-")):
        raise RuntimeError("Set a strong SESSION_SECRET")
    db_url = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/ace.db")
    if db_url.startswith("sqlite") and ":memory:" not in db_url:
        (ROOT / "data").mkdir(exist_ok=True)
    engine = create_engine(
        db_url, pool_pre_ping=True, connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {}
    )
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    gateway = RazorpayGateway(
        os.getenv("RAZORPAY_KEY_ID", ""), os.getenv("RAZORPAY_KEY_SECRET", ""),
        os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    )
    if env == "production" and not gateway.enabled:
        raise RuntimeError("Production requires Razorpay credentials and webhook secret")
    if env == "production" and (not os.getenv("ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD", "").startswith("replace-")):
        raise RuntimeError("Set a strong ADMIN_PASSWORD in production")
    serializer = URLSafeTimedSerializer(secret, salt="ace-cricketer-admin-v1")
    admin_user = os.getenv("ADMIN_USERNAME", "owner")
    admin_pass = os.getenv("ADMIN_PASSWORD", "")
    admin_hash = ph.hash(admin_pass) if admin_pass and not admin_pass.startswith("replace-") else None
    site_origin = os.getenv("SITE_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
    reservation_minutes = max(5, min(120, int(os.getenv("RESERVATION_MINUTES", "30"))))
    shipping_fee = max(0, int(os.getenv("SHIPPING_FEE_PAISE", "0")))
    free_shipping_above = max(0, int(os.getenv("FREE_SHIPPING_ABOVE_PAISE", "0")))
    attempt_log: dict[str, list[float]] = defaultdict(list)
    tracking_log: dict[str, list[float]] = defaultdict(list)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        Base.metadata.create_all(engine)  # Local bootstrap; use migrations in production.
        if demo:
            with SessionLocal() as db:
                seed_samples(db)
        yield
        engine.dispose()

    app = FastAPI(title="Ace Cricketer Store API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs" if env != "production" else None,
                  redoc_url=None, openapi_url="/api/openapi.json" if env != "production" else None)
    app.state.engine = engine
    app.state.db_factory = SessionLocal
    app.state.gateway = gateway
    app.state.demo_mode = demo
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        # Razorpay Checkout loads its own provider-controlled scripts and iframe.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "script-src 'self' https://checkout.razorpay.com https://*.razorpay.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; connect-src 'self' https://api.razorpay.com "
            "https://*.razorpay.com; frame-src https://api.razorpay.com https://*.razorpay.com"
        )
        if request.url.path.startswith("/api/admin"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def session_db():
        with SessionLocal() as db:
            yield db

    def request_origin_ok(req: Request) -> None:
        origin = req.headers.get("origin")
        if origin and origin.rstrip("/") != site_origin:
            raise HTTPException(403, "Origin not allowed; check SITE_ORIGIN")

    def require_admin(req: Request) -> dict:
        cookie = req.cookies.get("ace_admin", "")
        if not cookie:
            raise HTTPException(401, "Admin login required")
        try:
            data = serializer.loads(cookie, max_age=8 * 3600)
        except (BadSignature, SignatureExpired):
            raise HTTPException(401, "Admin session expired") from None
        if data.get("username") != admin_user:
            raise HTTPException(401, "Admin session invalid")
        return data

    def require_admin_write(req: Request, user: dict = Depends(require_admin)) -> dict:
        request_origin_ok(req)
        token = req.headers.get("x-csrf-token", "")
        if not token or not secrets.compare_digest(token, user["csrf"]):
            raise HTTPException(403, "Invalid CSRF token")
        return user

    def shipping_for(subtotal: int) -> int:
        if free_shipping_above and subtotal >= free_shipping_above:
            return 0
        return shipping_fee

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse(STATIC / "admin.html", media_type="text/html")

    @app.get("/api/config")
    def config():
        return {
            "demo_mode": demo, "payments_enabled": gateway.enabled and not demo,
            "public_key": gateway.key_id if gateway.enabled and not demo else "",
            "shipping_fee_paise": shipping_fee,
            "free_shipping_above_paise": free_shipping_above,
            "currency": "INR", "store_name": "ACE CRICKETER",
            "contact_phone": "+91 99866 83000",
        }

    @app.get("/api/products")
    def products(db: Session = Depends(session_db)):
        query = select(Product).where(Product.active.is_(True))
        if not demo:
            query = query.where(Product.sample.is_(False))
        rows = db.scalars(query.order_by(Product.featured.desc(), Product.id)).all()
        return {"products": [product_dict(p) for p in rows]}

    @app.post("/api/checkout", status_code=201)
    def checkout(payload: CheckoutRequest, db: Session = Depends(session_db)):
        if not demo and not gateway.enabled:
            raise HTTPException(503, "Payments are not configured")
        expire_reservations(db)
        ids = [item.product_id for item in payload.items]
        rows = db.scalars(select(Product).where(Product.id.in_(ids))).all()
        by_id = {p.id: p for p in rows}
        subtotal = 0
        item_snapshots = []
        try:
            for item in payload.items:
                p = by_id.get(item.product_id)
                if not p or not p.active or (p.sample and not demo):
                    raise HTTPException(409, "A product in your cart is no longer available")
                # Conditional atomic update prevents overselling under concurrency.
                result = db.execute(
                    update(Product).where(Product.id == p.id, Product.stock >= item.quantity)
                    .values(stock=Product.stock - item.quantity)
                )
                if result.rowcount != 1:
                    raise HTTPException(409, f"Insufficient stock for {p.name}")
                subtotal += p.price_paise * item.quantity
                item_snapshots.append((p, item.quantity))
            delivery = shipping_for(subtotal)
            customer = payload.customer
            reference = "AC-" + uuid.uuid4().hex[:12].upper()
            order = Order(
                reference=reference, customer_name=customer.name, email=customer.email,
                phone=customer.phone, address=customer.address, city=customer.city,
                state=customer.state, pincode=customer.pincode, notes=customer.notes,
                subtotal_paise=subtotal, shipping_paise=delivery, total_paise=subtotal + delivery,
                payment_status="pending", fulfillment_status="new",
                expires_at=utc_now() + timedelta(minutes=reservation_minutes),
            )
            for p, qty in item_snapshots:
                order.items.append(OrderItem(product_id=p.id, product_name=p.name,
                                             product_sku=p.sku, unit_paise=p.price_paise,
                                             quantity=qty))
            db.add(order)
            db.commit()
        except Exception:
            db.rollback()
            raise
        if demo:
            return {"mode": "demo", "order_reference": reference,
                    "message": "Preview order recorded as unpaid; no money was collected."}
        try:
            payment_order_id = gateway.create_order(order.total_paise, reference)
        except PaymentProviderError:
            order = db.scalar(select(Order).where(Order.reference == reference).options(selectinload(Order.items)))
            if order:
                release_stock(db, order, "failed")
                db.commit()
            raise HTTPException(502, "Payment service unavailable. Please try again.") from None
        order.razorpay_order_id = payment_order_id
        db.commit()
        return {"mode": "razorpay", "order_reference": reference,
                "razorpay_order_id": payment_order_id, "amount": order.total_paise,
                "currency": "INR", "key_id": gateway.key_id}

    @app.post("/api/payments/verify")
    def verify_payment(payload: PaymentVerification, db: Session = Depends(session_db)):
        if demo or not gateway.enabled:
            raise HTTPException(503, "Real payment verification is disabled")
        order = db.scalar(select(Order).where(Order.reference == payload.order_reference))
        if not order or not order.razorpay_order_id:
            raise HTTPException(404, "Order not found")
        if order.razorpay_order_id != payload.razorpay_order_id:
            raise HTTPException(400, "Order mismatch")
        if not gateway.verify_checkout(order.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature):
            raise HTTPException(400, "Invalid payment signature")
        try:
            remote = gateway.get_payment(payload.razorpay_payment_id)
        except PaymentProviderError:
            raise HTTPException(502, "Could not confirm payment status") from None
        if remote.get("order_id") != order.razorpay_order_id or remote.get("amount") != order.total_paise:
            raise HTTPException(400, "Payment information mismatch")
        if remote.get("status") == "captured":
            mark_captured(order, payload.razorpay_payment_id)
            db.commit()
        return {"order_reference": order.reference, "payment_status": order.payment_status,
                "provider_status": remote.get("status")}

    @app.post("/api/webhooks/razorpay", include_in_schema=False)
    async def payment_webhook(req: Request, db: Session = Depends(session_db)):
        if not gateway.enabled or demo:
            raise HTTPException(503, "Webhook not enabled")
        raw = await req.body()
        if len(raw) > 256_000:
            raise HTTPException(413, "Payload too large")
        if not gateway.verify_webhook(raw, req.headers.get("x-razorpay-signature", "")):
            raise HTTPException(400, "Invalid signature")
        try:
            body = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "Invalid JSON") from None
        event = body.get("event")
        payment = body.get("payload", {}).get("payment", {}).get("entity", {})
        razorpay_order_id = payment.get("order_id") or body.get("payload", {}).get("order", {}).get("entity", {}).get("id")
        if not razorpay_order_id:
            return {"accepted": True}
        order = db.scalar(select(Order).where(Order.razorpay_order_id == razorpay_order_id)
                          .options(selectinload(Order.items)))
        if not order:
            LOG.warning("Webhook for unknown provider order id")
            return {"accepted": True}
        if event in {"payment.captured", "order.paid"}:
            # For order.paid the order may have no payment entity; provider event
            # signature is still validated and this is the provider's paid state.
            event_order = body.get("payload", {}).get("order", {}).get("entity", {})
            amount = payment.get("amount") or event_order.get("amount")
            currency = payment.get("currency") or event_order.get("currency")
            if amount is not None and int(amount) != order.total_paise:
                LOG.error("Webhook amount mismatch for %s", order.reference)
                raise HTTPException(400, "Amount mismatch")
            if currency and currency != "INR":
                raise HTTPException(400, "Currency mismatch")
            mark_captured(order, payment.get("id", ""))
        elif event == "payment.failed":
            release_stock(db, order, "failed")
        db.commit()
        return {"accepted": True}

    @app.post("/api/orders/track")
    def track_order(payload: OrderTracking, req: Request, db: Session = Depends(session_db)):
        # Lightweight app-local throttle; also configure durable edge rate limits.
        ip = req.client.host if req.client else "unknown"
        now = monotonic()
        tracking_log[ip] = [stamp for stamp in tracking_log[ip] if stamp > now - 900]
        if len(tracking_log[ip]) >= 30:
            raise HTTPException(429, "Too many tracking attempts")
        tracking_log[ip].append(now)
        order = db.scalar(select(Order).where(Order.reference == payload.reference,
                                              Order.email == payload.email.lower().strip())
                          .options(selectinload(Order.items)))
        if not order:
            raise HTTPException(404, "Order not found for that email")
        return order_dict(order)

    @app.post("/api/admin/login")
    def login(payload: AdminLogin, req: Request, response: Response):
        request_origin_ok(req)
        ip = req.client.host if req.client else "unknown"
        now = monotonic()
        recent = [stamp for stamp in attempt_log[ip] if stamp > now - 900]
        attempt_log[ip] = recent
        if len(recent) >= 8:
            raise HTTPException(429, "Too many login attempts. Try later.")
        try:
            valid = bool(admin_hash and secrets.compare_digest(payload.username, admin_user)
                         and ph.verify(admin_hash, payload.password))
        except Exception:
            valid = False
        if not valid:
            recent.append(now)
            raise HTTPException(401, "Invalid credentials or admin password not configured")
        attempt_log.pop(ip, None)
        csrf = secrets.token_urlsafe(24)
        response.set_cookie("ace_admin", serializer.dumps({"username": admin_user, "csrf": csrf}),
                            httponly=True, secure=env == "production", samesite="strict",
                            max_age=8 * 3600, path="/")
        return {"authenticated": True, "csrf": csrf}

    @app.get("/api/admin/session")
    def admin_session(user: dict = Depends(require_admin)):
        return {"authenticated": True, "csrf": user["csrf"], "username": user["username"]}

    @app.post("/api/admin/logout")
    def logout(response: Response, _: dict = Depends(require_admin_write)):
        response.delete_cookie("ace_admin", path="/")
        return {"authenticated": False}

    @app.get("/api/admin/products")
    def admin_products(_: dict = Depends(require_admin), db: Session = Depends(session_db)):
        return {"products": [product_dict(p) for p in db.scalars(select(Product).order_by(Product.id.desc())).all()]}

    @app.post("/api/admin/products", status_code=201)
    def add_product(payload: AdminProduct, _: dict = Depends(require_admin_write),
                    db: Session = Depends(session_db)):
        product = Product(**payload.model_dump())
        db.add(product)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "SKU already in use") from None
        db.refresh(product)
        return product_dict(product)

    @app.put("/api/admin/products/{product_id}")
    def edit_product(product_id: int, payload: AdminProduct,
                     _: dict = Depends(require_admin_write), db: Session = Depends(session_db)):
        product = db.get(Product, product_id)
        if not product:
            raise HTTPException(404, "Product not found")
        for k, v in payload.model_dump().items():
            setattr(product, k, v)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "SKU already in use") from None
        return product_dict(product)

    @app.get("/api/admin/orders")
    def admin_orders(_: dict = Depends(require_admin), db: Session = Depends(session_db)):
        expire_reservations(db)
        orders = db.scalars(select(Order).options(selectinload(Order.items))
                            .order_by(Order.created_at.desc()).limit(250)).all()
        return {"orders": [order_dict(o, full=True) for o in orders]}

    @app.patch("/api/admin/orders/{reference}/fulfillment")
    def edit_order(reference: str, payload: FulfillmentUpdate,
                   _: dict = Depends(require_admin_write), db: Session = Depends(session_db)):
        order = db.scalar(select(Order).where(Order.reference == reference).options(selectinload(Order.items)))
        if not order:
            raise HTTPException(404, "Order not found")
        desired = payload.fulfillment_status
        if desired == "cancelled":
            if order.payment_status in {"captured", "review"}:
                raise HTTPException(409, "Paid order requires a refund workflow before cancellation")
            release_stock(db, order, "failed")
        elif desired != "new" and order.payment_status != "captured":
            raise HTTPException(409, "Cannot fulfill an order before payment is captured")
        if order.fulfillment_status == "cancelled" and desired != "cancelled":
            raise HTTPException(409, "Cancelled orders cannot be reopened")
        order.fulfillment_status = desired
        db.commit()
        return order_dict(order, full=True)

    @app.get("/healthz", include_in_schema=False)
    def health():
        return {"status": "ok"}

    return app


app = create_app()
