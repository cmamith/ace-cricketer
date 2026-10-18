from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app, release_stock
from app.models import Order, Product, utc_now
from app.payment import RazorpayGateway


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ADMIN_USERNAME", "owner")
    monkeypatch.setenv("ADMIN_PASSWORD", "local-test-password-not-for-use")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-with-sufficient-length-123456")
    monkeypatch.setenv("SITE_ORIGIN", "http://127.0.0.1:8000")
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
    app = create_app(database_url=f"sqlite:///{tmp_path / 'test.db'}", demo_mode=True)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
def checkout_body():
    return {"items": [{"product_id": 1, "quantity": 2}], "customer": {
        "name": "Example Buyer", "email": "buyer@example.com", "phone": "9876543210",
        "address": "12 Example Street, First Floor", "city": "Bengaluru",
        "state": "Karnataka", "pincode": "560017", "notes": "",
    }}


def login(client):
    response = client.post('/api/admin/login', json={"username": "owner", "password": "local-test-password-not-for-use"})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf"]}


def test_home_and_catalog(client):
    assert client.get('/').status_code == 200
    assert client.get('/assets/bat.svg').status_code == 200
    data = client.get('/api/products').json()["products"]
    assert len(data) == 8
    assert all(p['sample'] for p in data)
    assert client.get('/api/config').json()['payments_enabled'] is False


def test_checkout_price_is_server_derived_and_order_persists(client, checkout_body):
    original = client.get('/api/products').json()['products'][0]
    response = client.post('/api/checkout', json={**checkout_body, "subtotal_paise": 1})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data['mode'] == 'demo'
    tracked = client.post('/api/orders/track', json={"reference": data['order_reference'], "email": 'BUYER@example.com'})
    assert tracked.status_code == 200
    assert tracked.json()['total_paise'] == original['price_paise'] * 2
    assert tracked.json()['payment_status'] == 'pending'
    assert client.post('/api/orders/track', json={"reference": data['order_reference'], "email": 'someone@else.com'}).status_code == 404
    after = client.get('/api/products').json()['products'][0]
    assert after['stock'] == original['stock'] - 2


def test_atomic_stock_and_failed_validation(client, checkout_body):
    assert client.post('/api/checkout', json={**checkout_body, 'items': [{"product_id": 1, "quantity": 10}]}).status_code == 409
    assert client.post('/api/checkout', json={**checkout_body, 'items': [{"product_id": 1, "quantity": 1},{"product_id": 1, "quantity": 1}]}).status_code == 422
    assert client.post('/api/checkout', json={**checkout_body, 'customer': {**checkout_body['customer'], 'pincode': 'abc'}}).status_code == 422
    assert client.get('/api/products').json()['products'][0]['stock'] == 8


def test_admin_auth_csrf_and_product_editor(client):
    assert client.get('/api/admin/orders').status_code == 401
    csrf = login(client)
    data = client.get('/api/admin/products').json()['products']
    assert len(data) == 8
    product = {**{k:data[0][k] for k in ['sku','name','category','description','price_paise','compare_at_paise','stock','image_url','featured','active','sample']},
               'sku':'NEW-SKU-1','name':'Genuine Merchant Bat','sample':False,'price_paise':950000}
    assert client.post('/api/admin/products', json=product).status_code == 403
    saved = client.post('/api/admin/products', headers=csrf, json=product)
    assert saved.status_code == 201, saved.text
    new_id = saved.json()['id']
    changed = client.put(f'/api/admin/products/{new_id}', headers=csrf,json={**product,'stock':3,'featured':True})
    assert changed.status_code == 200
    assert changed.json()['stock'] == 3
    assert client.post('/api/admin/products', headers=csrf,json=product).status_code == 409
    assert client.post('/api/admin/logout', headers=csrf).status_code == 200
    assert client.get('/api/admin/orders').status_code == 401


def test_order_fulfillment_and_cancel_release(client, checkout_body):
    csrf = login(client)
    order_ref = client.post('/api/checkout', json=checkout_body).json()['order_reference']
    denied = client.patch(f'/api/admin/orders/{order_ref}/fulfillment',headers=csrf,
                          json={'fulfillment_status':'shipped'})
    assert denied.status_code == 409
    ok = client.patch(f'/api/admin/orders/{order_ref}/fulfillment',headers=csrf,
                      json={'fulfillment_status':'cancelled'})
    assert ok.status_code == 200
    assert ok.json()['payment_status'] == 'failed'
    assert client.get('/api/products').json()['products'][0]['stock'] == 8
    # Cancelling again is idempotent, does not increase stock twice.
    assert client.patch(f'/api/admin/orders/{order_ref}/fulfillment',headers=csrf,
                        json={'fulfillment_status':'cancelled'}).status_code == 200
    assert client.get('/api/products').json()['products'][0]['stock'] == 8


def test_expiration_releases_reserved_units(client, checkout_body):
    ref = client.post('/api/checkout', json=checkout_body).json()['order_reference']
    with client.app.state.db_factory() as db:
        order = db.scalar(select(Order).where(Order.reference == ref))
        order.expires_at = utc_now() - timedelta(minutes=1)
        db.commit()
    login(client)
    client.get('/api/admin/orders')  # triggers expiry reconciliation
    assert client.get('/api/products').json()['products'][0]['stock'] == 8
    assert client.post('/api/orders/track',json={'reference':ref,'email':'buyer@example.com'}).json()['payment_status'] == 'expired'


def test_gateway_signatures():
    gateway = RazorpayGateway('rzp_test_example','checkout_secret','webhook_secret')
    sig = hmac.new(b'checkout_secret',b'order123|pay123',hashlib.sha256).hexdigest()
    assert gateway.verify_checkout('order123','pay123',sig)
    assert not gateway.verify_checkout('order123','pay456',sig)
    raw = b'{"event":"order.paid"}'
    webhook_sig = hmac.new(b'webhook_secret',raw,hashlib.sha256).hexdigest()
    assert gateway.verify_webhook(raw,webhook_sig)
    assert not gateway.verify_webhook(raw,webhook_sig[:-1] + '0') or webhook_sig.endswith('0')


def test_wrong_origin_rejected(client):
    bad = client.post('/api/admin/login',json={'username':'owner','password':'local-test-password-not-for-use'},headers={'Origin':'https://malicious.example'})
    assert bad.status_code == 403


def test_live_checkout_verification_and_signed_webhook(tmp_path, monkeypatch, checkout_body):
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('SESSION_SECRET','test-session-secret-with-sufficient-length-123456')
    monkeypatch.setenv('ADMIN_PASSWORD','live-test-owner-password')
    monkeypatch.setenv('RAZORPAY_KEY_ID','rzp_test_fake')
    monkeypatch.setenv('RAZORPAY_KEY_SECRET','fake_api_secret')
    monkeypatch.setenv('RAZORPAY_WEBHOOK_SECRET','fake_webhook_secret')
    app=create_app(database_url=f"sqlite:///{tmp_path/'live.db'}",demo_mode=False)
    with TestClient(app) as tc:
        auth=tc.post('/api/admin/login',json={'username':'owner','password':'live-test-owner-password'})
        assert auth.status_code==200
        csrf={'X-CSRF-Token':auth.json()['csrf']}
        prod=tc.post('/api/admin/products',headers=csrf,json={
            'sku':'MATCH-BAT-10','name':'Shop-approved willow bat','category':'Bats',
            'description':'Official merchant product','price_paise':500000,'stock':6,
            'compare_at_paise':600000,'image_url':'','featured':True,'active':True,'sample':False,
        })
        assert prod.status_code==201,prod.text
        product_id=prod.json()['id']
        app.state.gateway.create_order=lambda total,receipt:'order_test_alpha'
        app.state.gateway.get_payment=lambda pid:{'order_id':'order_test_alpha','amount':500000,'status':'captured'}
        res=tc.post('/api/checkout',json={**checkout_body,'items':[{'product_id':product_id,'quantity':1}]})
        assert res.status_code==201,res.text
        payload=res.json()
        assert payload['mode']=='razorpay'
        assert payload['amount']==500000
        valid_sig=hmac.new(b'fake_api_secret',b'order_test_alpha|pay_test_alpha',hashlib.sha256).hexdigest()
        bad=tc.post('/api/payments/verify',json={
            'order_reference':payload['order_reference'], 'razorpay_order_id':'order_test_alpha',
            'razorpay_payment_id':'pay_test_alpha','razorpay_signature':'forged',
        })
        assert bad.status_code==400
        ok=tc.post('/api/payments/verify',json={
            'order_reference':payload['order_reference'], 'razorpay_order_id':'order_test_alpha',
            'razorpay_payment_id':'pay_test_alpha','razorpay_signature':valid_sig,
        })
        assert ok.status_code==200,ok.text
        assert ok.json()['payment_status']=='captured'
        body=b'{"event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_test_alpha","order_id":"order_test_alpha","amount":500000}}}}'
        signed=hmac.new(b'fake_webhook_secret',body,hashlib.sha256).hexdigest()
        assert tc.post('/api/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':'wrong'}).status_code==400
        assert tc.post('/api/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':signed}).status_code==200
        assert tc.post('/api/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':signed}).status_code==200
        shipped=tc.patch(f"/api/admin/orders/{payload['order_reference']}/fulfillment",headers=csrf,
                        json={'fulfillment_status':'shipped'})
        assert shipped.status_code==200
        assert shipped.json()['payment_status']=='captured'
        assert shipped.json()['fulfillment_status']=='shipped'
        assert tc.get('/api/products').json()['products'][0]['stock']==5
