
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from company.models import Company
from products.models import Category, Product
from inventory.models import Inventory
from inventory.services import record_stock_movement


class TenantIsolationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        # Two temporary company-owner accounts
        cls.user_a = User.objects.create_user(
            email="owner_a@example.com",
            password="TestPassword123!"
        )

        cls.user_b = User.objects.create_user(
            email="owner_b@example.com",
            password="TestPassword123!"
        )

        # Two temporary companies
        cls.company_a = Company.objects.create(
            user=cls.user_a,
            company_name="Test Shoe Store",
            address="Test Address A",
            company_registration_number="TEST-A-001",
            state="Kerala",
            country="India",
            currency="INR",
            phone="9000000001",
            email="shop_a@example.com",
        )

        cls.company_b = Company.objects.create(
            user=cls.user_b,
            company_name="Test Electronics Store",
            address="Test Address B",
            company_registration_number="TEST-B-001",
            state="Kerala",
            country="India",
            currency="INR",
            phone="9000000002",
            email="shop_b@example.com",
        )

        # Each company owns its own category
        category_a = Category.objects.create(
            company=cls.company_a,
            name="Shoes",
        )

        category_b = Category.objects.create(
            company=cls.company_b,
            name="Electronics",
        )

        # Each company owns a separate product
        cls.product_a = Product.objects.create(
            company=cls.company_a,
            category=category_a,
            name="Test Running Shoes",
            sku="TEST-SH-001",
            purchase_price=1000,
            selling_price=1500,
        )

        cls.product_b = Product.objects.create(
            company=cls.company_b,
            category=category_b,
            name="Test Headphones",
            sku="TEST-EL-001",
            purchase_price=500,
            selling_price=800,
        )

        Inventory.objects.create(
            company=cls.company_a,
            product=cls.product_a,
            quantity=20,
        )

        Inventory.objects.create(
            company=cls.company_b,
            product=cls.product_b,
            quantity=30,
        )

    def test_company_a_product_list_is_isolated(self):
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("product_list")
        )

        self.assertEqual(response.status_code, 200)

        products = list(
            response.context["products"]
        )

        self.assertIn(self.product_a, products)
        self.assertNotIn(self.product_b, products)

    def test_company_a_inventory_list_is_isolated(self):
        self.client.force_login(self.user_a)

        response = self.client.get(
            reverse("stock_movement")
        )

        self.assertEqual(response.status_code, 200)

        inventory_items = list(
            response.context["inventory_items"]
        )

        product_ids = [
            item.product_id
            for item in inventory_items
        ]

        self.assertIn(self.product_a.pk, product_ids)
        self.assertNotIn(self.product_b.pk, product_ids)

    def test_cannot_modify_another_company_stock(self):
        inventory_b = Inventory.objects.get(
            company=self.company_b,
            product=self.product_b,
        )

        original_quantity = inventory_b.quantity

        with self.assertRaises(ValidationError):
            record_stock_movement(
                company=self.company_a,
                product=self.product_b,
                movement_type="OUT",
                quantity=5,
                reason="Unauthorized stock test",
            )

        inventory_b.refresh_from_db()

        self.assertEqual(
            inventory_b.quantity,
            original_quantity,
        )

    def test_inventory_post_rejects_other_company_product(self):
        # Company A is logged in
        self.client.force_login(self.user_a)

        # Check Company B's stock before the request
        inventory_b = Inventory.objects.get(
            company=self.company_b,
            product=self.product_b,
        )

        original_quantity = inventory_b.quantity

        # Company A tries to submit Company B's product
        response = self.client.post(
            reverse("stock_movement"),
            {
                "product": str(self.product_b.pk),
                "movement_type": "OUT",
                "quantity": 5,
                "reason": "Cross-company security test",
            },
        )

        # The form should reject the foreign product
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "product",
            response.context["form"].errors,
        )

        # Company B's stock must remain unchanged
        inventory_b.refresh_from_db()

        self.assertEqual(
            inventory_b.quantity,
            original_quantity,
        )

    def test_inline_save_rejects_other_company_category(self):
        import json

        # Log in as Company A
        self.client.force_login(self.user_a)

        # Attempt to use Company B's category
        payload = {
            "products": [
                {
                    "name": "Unauthorized Test Product",
                    "sku": "CROSS-TENANT-001",
                    "category": str(
                        self.product_b.category_id
                    ),
                    "brand": "Test Brand",
                    "purchase_price": "100.00",
                    "selling_price": "150.00",
                    "unit": "Piece",
                    "low_stock_threshold": 10,
                    "description": "Security test",
                    "is_active": True,
                }
            ]
        }

        response = self.client.post(
            reverse("inline_save"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        # Product creation must be rejected
        self.assertEqual(response.status_code, 400)

        # No unauthorized product should be created
        self.assertFalse(
            Product.objects.filter(
                company=self.company_a,
                sku="CROSS-TENANT-001",
            ).exists()
        )

    def test_csv_import_rejects_other_company_category(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        # Log in as Company A.
        self.client.force_login(self.user_a)

        # "Electronics" belongs to Company B in our test data.
        csv_content = (
            "name,sku,category,purchase_price,selling_price\n"
            "Unauthorized Phone,CROSS-CSV-001,Electronics,500,800\n"
        )

        upload = SimpleUploadedFile(
            "products.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        # Company A attempts to preview the import.
        response = self.client.post(
            reverse("import_products"),
            {
                "action": "preview",
                "file": upload,
            },
        )

        self.assertEqual(response.status_code, 200)

        # The foreign category must be rejected.
        self.assertEqual(
            response.context["valid_count"],
            0,
        )

        self.assertEqual(
            response.context["error_count"],
            1,
        )

        # No rows should be approved for import.
        self.assertEqual(
            self.client.session.get("product_import_rows"),
            [],
        )

        # No unauthorized product was saved.
        self.assertFalse(
            Product.objects.filter(
                sku="CROSS-CSV-001"
            ).exists()
        )

    def test_import_confirm_rejects_foreign_category(self):

        # Log in as Company A
        self.client.force_login(self.user_a)

        # Simulate an import row with Company B's category
        session = self.client.session

        session["product_import_rows"] = [
            {
                "name": "Unauthorized Imported Product",
                "sku": "CROSS-CONFIRM-001",
                "category": str(self.product_b.category_id),
                "brand": "Test Brand",
                "purchase_price": "100.00",
                "selling_price": "150.00",
                "unit": "Piece",
                "low_stock_threshold": 10,
                "description": "Cross-company test",
                "is_active": True,
            }
        ]

        session.save()

        # Attempt to confirm the import
        response = self.client.post(
            reverse("import_products"),
            {"action": "confirm"},
        )

        # The existing view redirects after rejecting the row
        self.assertEqual(response.status_code, 302)

        # Verify the unauthorized product was NOT saved
        self.assertFalse(
            Product.objects.filter(
                sku="CROSS-CONFIRM-001"
            ).exists()
        )

    def test_company_can_import_own_products(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        # Log in as Company A
        self.client.force_login(self.user_a)

        # "Shoes" belongs to Company A
        csv_content = (
            "name,sku,category,purchase_price,selling_price\n"
            "New Running Shoes,TEST-IMPORT-001,Shoes,1000,1500\n"
        )

        upload = SimpleUploadedFile(
            "products.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        # Step 1: Preview the CSV
        preview_response = self.client.post(
            reverse("import_products"),
            {
                "action": "preview",
                "file": upload,
            },
        )

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(
            preview_response.context["valid_count"],
            1,
        )
        self.assertEqual(
            preview_response.context["error_count"],
            0,
        )

        # Step 2: Confirm the import
        confirm_response = self.client.post(
            reverse("import_products"),
            {"action": "confirm"},
        )

        self.assertEqual(confirm_response.status_code, 302)

        # Step 3: Verify the product belongs to Company A
        self.assertTrue(
            Product.objects.filter(
                company=self.company_a,
                sku="TEST-IMPORT-001",
            ).exists()
        )

        # Step 4: Verify it does NOT belong to Company B
        self.assertFalse(
            Product.objects.filter(
                company=self.company_b,
                sku="TEST-IMPORT-001",
            ).exists()
        )

        # Step 5: Confirm the session was cleared
        self.assertNotIn(
            "product_import_rows",
            self.client.session,
        )


class StockMovementPopupTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="stockowner@test.com",
            password="Password@123",
            first_name="Stock",
            last_name="Owner",
            is_verified=True,
        )
        self.company = Company.objects.create(
            user=self.user,
            company_name="Stock Corp",
            company_registration_number="SC01",
            state="Kerala",
            country="India",
            currency="INR",
            phone="1234567890",
            email="stockowner@test.com",
            address="456 Market St",
        )
        self.user.company = self.company
        self.user.save()

        self.category = Category.objects.create(
            company=self.company,
            name="General"
        )
        self.product = Product.objects.create(
            company=self.company,
            category=self.category,
            name="Sample Widget",
            sku="WIDGET-01",
            selling_price="150.00",
            purchase_price="80.00",
            is_active=True,
        )
        self.inventory = Inventory.objects.create(
            company=self.company,
            product=self.product,
            quantity=10,
        )
        self.client.force_login(self.user)

    def test_stock_movement_popup_render(self):
        url = reverse("stock_movement") + "?popup=1"
        response = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_X_RF_WINDOW="1")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context.get("is_popup"))
        self.assertContains(response, "Record Stock Movement")
        self.assertContains(response, "name=\"movement_type\"")

    def test_stock_movement_ajax_post_success(self):
        url = reverse("stock_movement")
        data = {
            "product": self.product.pk,
            "movement_type": "IN",
            "quantity": 15,
            "reason": "Restock shipment",
            "popup": "1",
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_X_RF_WINDOW="1")
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertTrue(json_data.get("success"))
        self.assertEqual(json_data.get("quantity"), 25)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 25)

    def test_stock_movement_ajax_post_validation_error(self):
        url = reverse("stock_movement")
        data = {
            "product": self.product.pk,
            "movement_type": "OUT",
            "quantity": 999,  # exceeds available 10
            "reason": "Overselling attempt",
            "popup": "1",
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_X_RF_WINDOW="1")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Insufficient stock", status_code=400)

