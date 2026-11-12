from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from company.models import Company
from .models import Category, Product


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ProductCategoryPopupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="product-owner@example.com", password="password", is_verified=True)
        self.company = Company.objects.create(user=self.user, company_name="Test Retail", currency="INR")
        self.client.force_login(self.user)

    def test_add_category_popup_rendering(self):
        """Add Category popup renders with minimal popup layout."""
        response = self.client.get(reverse("add_category") + "?popup=1")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "layouts/popup_base.html")
        self.assertNotContains(response, 'id="sidebar"')
        self.assertContains(response, "Category Name")

    def test_add_category_popup_ajax_success(self):
        """Add Category via AJAX inside popup saves to database and returns JSON."""
        data = {
            "name": "Stationery",
            "description": "Office and school supplies",
            "is_active": True
        }
        response = self.client.post(
            reverse("add_category"),
            data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertTrue(json_data.get("success"))
        self.assertEqual(json_data.get("name"), "Stationery")

        category = Category.objects.get(company=self.company, name="Stationery")
        self.assertEqual(category.description, "Office and school supplies")
        self.assertTrue(category.is_active)

    def test_add_category_popup_ajax_invalid(self):
        """Invalid category submission inside popup keeps popup open with errors."""
        initial_count = Category.objects.filter(company=self.company).count()
        response = self.client.post(
            reverse("add_category") + "?popup=1",
            {"name": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertEqual(Category.objects.filter(company=self.company).count(), initial_count)


    def test_product_form_popup_rendering(self):
        """Add and edit product popup forms render with minimal layout."""
        cat = Category.objects.create(company=self.company, name="Apparel")
        prod = Product.objects.create(
            company=self.company, category=cat, name="T-Shirt", sku="TSH-01",
            purchase_price=10, selling_price=20
        )
        for url in [
            reverse("add_product") + "?popup=1",
            reverse("edit_product", args=[prod.pk]) + "?popup=1",
        ]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertTemplateUsed(resp, "layouts/popup_base.html")
            self.assertNotContains(resp, 'id="sidebar"')

    def test_add_product_popup_ajax_success(self):
        """Add product via popup AJAX saves to database and returns JSON."""
        cat = Category.objects.create(company=self.company, name="Apparel")
        data = {
            "name": "Hoodie",
            "sku": "HOD-01",
            "category": cat.pk,
            "purchase_price": "25.00",
            "selling_price": "50.00",
            "unit": "PIECE",
            "low_stock_threshold": 5,
            "is_active": True
        }
        resp = self.client.post(reverse("add_product"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        created = Product.objects.get(company=self.company, sku="HOD-01")
        self.assertEqual(created.name, "Hoodie")

    def test_edit_product_popup_ajax_success(self):
        """Edit product via popup AJAX updates record and returns JSON."""
        cat = Category.objects.create(company=self.company, name="Apparel")
        prod = Product.objects.create(
            company=self.company, category=cat, name="Cap", sku="CAP-01",
            purchase_price=5, selling_price=10
        )
        data = {
            "name": "Baseball Cap",
            "sku": "CAP-01",
            "category": cat.pk,
            "purchase_price": "6.00",
            "selling_price": "12.00",
            "unit": "PIECE",
            "low_stock_threshold": 5,
            "is_active": True
        }
        resp = self.client.post(reverse("edit_product", args=[prod.pk]), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        prod.refresh_from_db()
        self.assertEqual(prod.name, "Baseball Cap")
