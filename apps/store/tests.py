from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User

from .models import Product


class StoreCatalogueTests(TestCase):
    def test_catalogue_offers_every_product_the_app_sells(self):
        # The app looks products up by kind; an empty list made every purchase fail
        # with product_not_found before M-PESA was contacted.
        client = APIClient()
        client.force_authenticate(user=User.objects.create_user(email="buyer@example.test"))
        response = client.get("/api/v1/store/products/")
        self.assertEqual(response.status_code, 200)
        kinds = {item["kind"] for item in response.data}
        self.assertEqual(kinds, {"premium", "boost", "unmask_fast_track"})
        boost = Product.objects.get(kind="boost")
        self.assertEqual((boost.price_kes, boost.duration_days, boost.is_active), (50, None, True))
        self.assertEqual(Product.objects.get(kind="premium").duration_days, 7)
