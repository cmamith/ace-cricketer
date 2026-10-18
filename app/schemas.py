from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

CATEGORIES = {"Bats", "Gloves", "Pads", "Helmets", "Balls", "Accessories"}


class CartItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=10)


class Customer(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=200)
    phone: str = Field(pattern=r"^[6-9]\d{9}$")
    address: str = Field(min_length=8, max_length=300)
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    pincode: str = Field(pattern=r"^\d{6}$")
    notes: str = Field(default="", max_length=500)

    @field_validator("email")
    @classmethod
    def reasonable_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1] or " " in value:
            raise ValueError("Enter a valid email address")
        return value


class CheckoutRequest(BaseModel):
    items: list[CartItem] = Field(min_length=1, max_length=25)
    customer: Customer

    @model_validator(mode="after")
    def no_duplicate_items(self):
        if len({item.product_id for item in self.items}) != len(self.items):
            raise ValueError("Duplicate cart items")
        return self


class OrderTracking(BaseModel):
    reference: str = Field(min_length=10, max_length=40)
    email: str = Field(min_length=5, max_length=200)


class PaymentVerification(BaseModel):
    order_reference: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class AdminLogin(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=300)


class AdminProduct(BaseModel):
    sku: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
    name: str = Field(min_length=3, max_length=160)
    category: str
    description: str = Field(default="", max_length=3000)
    price_paise: int = Field(gt=0, le=100_000_000)
    compare_at_paise: int | None = Field(default=None, ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=100_000)
    image_url: str = Field(default="", max_length=500)
    featured: bool = False
    active: bool = True
    sample: bool = False

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError("Unsupported category")
        return value

    @field_validator("image_url")
    @classmethod
    def safe_image_url(cls, value: str) -> str:
        value = value.strip()
        if value and not (value.startswith("https://") or value.startswith("/assets/")):
            raise ValueError("Use HTTPS or /assets/ images")
        return value


class FulfillmentUpdate(BaseModel):
    fulfillment_status: str

    @field_validator("fulfillment_status")
    @classmethod
    def allowed_status(cls, value: str) -> str:
        if value not in {"new", "processing", "shipped", "delivered", "cancelled"}:
            raise ValueError("Unsupported status")
        return value
