from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .models import Product

# Design-only catalog entries, deliberately not representations of shop stock/prices.
SAMPLES = [
    ("DEMO-BAT-01", "English Willow Bat", "Bats", 649900, 799900, 8, True,
     "Balanced pickup and premium willow styling for serious match-day play."),
    ("DEMO-BAT-02", "Kashmir Willow Bat", "Bats", 299900, 379900, 12, False,
     "A durable training and club cricket option."),
    ("DEMO-GLO-01", "Pro Batting Gloves", "Gloves", 189900, 249900, 18, True,
     "Flexible finger protection and a secure wrist strap."),
    ("DEMO-PAD-01", "Elite Batting Pads", "Pads", 329900, 399900, 9, True,
     "Lightweight protection for confident footwork."),
    ("DEMO-HLM-01", "Match Cricket Helmet", "Helmets", 399900, 499900, 7, True,
     "Comfort-focused cricket helmet concept with faceguard."),
    ("DEMO-BAL-01", "Leather Cricket Ball", "Balls", 89900, 119900, 32, False,
     "Match-style red leather cricket ball concept."),
    ("DEMO-BAG-01", "Cricket Kit Bag", "Accessories", 229900, 299900, 10, False,
     "Keep training and match essentials organised."),
    ("DEMO-ACC-01", "Bat Grip & Care Kit", "Accessories", 69900, 89900, 20, False,
     "Basic bat-care accessories and replacement grip concept."),
]


def seed_samples(db: Session) -> None:
    if db.scalar(select(func.count(Product.id))):
        return
    for sku, name, cat, price, compare, stock, featured, desc in SAMPLES:
        db.add(Product(sku=sku, name=name, category=cat, description=desc,
                       price_paise=price, compare_at_paise=compare, stock=stock,
                       featured=featured, active=True, sample=True))
    db.commit()
