# The store catalogue was never seeded, so GET /store/products/ returned [] and the
# app failed every purchase with product_not_found before reaching M-PESA.
# Prices and durations mirror the copy on the app's store screen.

from django.db import migrations

PRODUCTS = [
    {
        "code": "premium-weekly",
        "name": "Weekly Premium",
        "price_kes": 150,
        "kind": "premium",
        "duration_days": 7,
    },
    {
        "code": "boost-single",
        "name": "Profile Boost",
        "price_kes": 50,
        "kind": "boost",
        "duration_days": None,
    },
    {
        "code": "unmask-fast-track",
        "name": "Early reveal request",
        "price_kes": 50,
        "kind": "unmask_fast_track",
        "duration_days": None,
    },
]


def seed_products(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    for item in PRODUCTS:
        # Only add what is missing: existing rows keep whatever price/name they have.
        if not Product.objects.filter(kind=item["kind"]).exists():
            Product.objects.create(**item)


class Migration(migrations.Migration):
    dependencies = [("store", "0003_align_model_state")]
    operations = [migrations.RunPython(seed_products, migrations.RunPython.noop)]
