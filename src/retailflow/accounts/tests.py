from django.test import TestCase
from django.urls import reverse
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone

from accounts.models import User
from company.models import Company, Branch
from employees.models import Employee
from products.models import Category, Product
from inventory.models import Inventory, StockMovement


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@example.com", password="test-password")
        self.company = Company.objects.create(
            user=self.user, company_name="Owner Store", company_registration_number="OWNER",
            country="IN", currency="INR",
        )
        self.category = Category.objects.create(company=self.company, name="Food")
        self.client.force_login(self.user)

    def product(self, name, **kwargs):
        return Product.objects.create(company=self.company, category=self.category,
                                      name=name, sku=name, purchase_price="12.50",
                                      selling_price="20.00", **kwargs)

    def test_empty_dashboard_and_product_navigation(self):
        response = self.client.get(reverse("dashboard_view"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stock_units"], 0)
        self.assertEqual(response.context["stock_value"], Decimal("0"))
        self.assertContains(response, "No stock movements recorded in the last seven days.")
        self.assertContains(response, 'href="/products/"')
        self.assertNotContains(response, "INV-1048")
        self.assertNotContains(response, "Sample data")
        self.assertNotContains(response, 'href="#products"')
        self.assertEqual(self.client.get(reverse("product_list")).status_code, 200)

    def test_real_totals_alerts_and_chart_exclude_other_companies(self):
        product = self.product("Low rice")
        inventory = Inventory.objects.create(company=self.company, product=product,
                                             quantity=4, damaged_quantity=2)
        self.product("Missing inventory")
        inactive = self.product("Inactive", is_active=False)
        Inventory.objects.create(company=self.company, product=inactive, quantity=900)
        Employee.objects.create(company=self.company, employee_id="ID001", first_name="Admin",
                                last_name="Team", role="MANAGER", is_online=True)
        Branch.objects.create(company=self.company, name="Store", code="ONE")
        StockMovement.objects.create(inventory=inventory, movement_type="IN", quantity=4)
        old = StockMovement.objects.create(inventory=inventory, movement_type="IN", quantity=500)
        StockMovement.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=8))
        other_user = User.objects.create_user(email="other@example.com", password="test-password")
        other = Company.objects.create(user=other_user, company_name="Private tenant",
                                       company_registration_number="OTHER", currency="USD")
        category = Category.objects.create(company=other, name="Private")
        other_product = Product.objects.create(company=other, category=category, name="Secret product",
                                               sku="secret", purchase_price=100, selling_price=120)
        other_inventory = Inventory.objects.create(company=other, product=other_product, quantity=999)
        StockMovement.objects.create(inventory=other_inventory, movement_type="IN", quantity=999)
        response = self.client.get(reverse("dashboard_view"))
        context = response.context
        self.assertEqual(context["total_products"], 2)
        self.assertEqual(context["stock_units"], 4)
        self.assertEqual(context["stock_value"], Decimal("50.00"))
        self.assertEqual(context["damaged_units"], 2)
        self.assertEqual(context["low_stock_count"], 1)
        self.assertEqual(context["out_of_stock_count"], 1)
        self.assertEqual(context["employee_count"], 1)
        self.assertEqual(context["online_count"], 1)
        self.assertEqual(context["branch_count"], 1)
        self.assertEqual(context["chart_total"], 4)
        self.assertEqual(len(context["chart_days"]), 7)
        self.assertContains(response, 'class="sales-line"')
        self.assertNotContains(response, "Secret product")
        self.assertNotContains(response, "Private tenant")

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("dashboard_view")).status_code, 302)

    def test_owner_without_company_is_sent_to_registration(self):
        user = User.objects.create_user(email="new@example.com", password="test-password")
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse("dashboard_view")),
                             reverse("company_registration"), fetch_redirect_response=False)


class AdminLayoutSidebarTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="admin@example.com", password="password123")
        self.company = Company.objects.create(
            user=self.user,
            company_name="Apex Retail Corp",
            company_registration_number="APEX-001",
            country="IN",
            currency="INR",
        )
        self.branch = Branch.objects.create(
            company=self.company,
            name="Main Outlet",
            code="MO-01",
        )
        self.client.force_login(self.user)

    def test_sidebar_presence_across_all_admin_pages(self):
        """Verify that every company admin page includes the persistent sidebar and topbar."""
        admin_urls = [
            reverse("dashboard_view"),
            reverse("product_list"),
            reverse("add_category"),
            reverse("import_products"),
            reverse("stock_movement"),
            reverse("branch_list"),
            reverse("add_branch"),
            reverse("edit_branch", kwargs={"branch_id": self.branch.pk}),
            reverse("employee_list"),
            reverse("create_employee"),
        ]

        for url in admin_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                # Sidebar structure
                self.assertContains(response, 'id="sidebar"')
                self.assertContains(response, 'RetailFlow')
                self.assertContains(response, 'Apex Retail Corp')
                self.assertContains(response, 'Administrator')
                self.assertContains(response, 'class="topbar"')
                self.assertContains(response, 'toggleSidebar()')
                # Navigation links
                self.assertContains(response, 'href="/accounts/dashboard/"')
                self.assertContains(response, 'href="/products/"')
                self.assertContains(response, 'href="/inventory/movement/"')
                self.assertContains(response, 'href="/employees/"')
                self.assertContains(response, 'href="/company/branches/"')
                self.assertContains(response, 'href="/accounts/logout/"')

    def test_active_menu_item_highlighting(self):
        """Verify that navigating to different admin pages highlights the corresponding menu item."""
        pages_and_expected_active_snippets = [
            (reverse("dashboard_view"), 'href="/accounts/dashboard/"\n       class="menu-item active"'),
            (reverse("product_list"), 'href="/products/"\n       class="menu-item active"'),
            (reverse("add_category"), 'href="/products/"\n       class="menu-item active"'),
            (reverse("import_products"), 'href="/products/"\n       class="menu-item active"'),
            (reverse("stock_movement"), 'href="/inventory/movement/"\n       class="menu-item active"'),
            (reverse("branch_list"), 'href="/company/branches/"\n       class="menu-item active"'),
            (reverse("add_branch"), 'href="/company/branches/"\n       class="menu-item active"'),
            (reverse("edit_branch", kwargs={"branch_id": self.branch.pk}), 'href="/company/branches/"\n       class="menu-item active"'),
            (reverse("employee_list"), 'href="/employees/"\n       class="menu-item active"'),
            (reverse("create_employee"), 'href="/employees/"\n       class="menu-item active"'),
        ]

        for url, snippet in pages_and_expected_active_snippets:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, snippet)

    def test_public_and_registration_pages_do_not_expose_sidebar(self):
        """Verify that login, signup, landing, and company registration do NOT show admin sidebar."""
        self.client.logout()

        public_urls = [
            reverse("landing"),
            reverse("login"),
            reverse("signup"),
        ]
        for url in public_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotContains(response, 'id="sidebar"')
                self.assertNotContains(response, 'class="toggle-btn"')

        # Unregistered user on company registration
        new_user = User.objects.create_user(email="unregistered@example.com", password="password123")
        self.client.force_login(new_user)
        reg_response = self.client.get(reverse("company_registration"))
        self.assertEqual(reg_response.status_code, 200)
        self.assertNotContains(reg_response, 'id="sidebar"')

    def test_multi_company_tenancy_in_sidebar(self):
        """Ensure company name in sidebar matches the logged-in tenant and never leaks other companies."""
        other_user = User.objects.create_user(email="other_owner@example.com", password="password123")
        Company.objects.create(
            user=other_user,
            company_name="Zephyr Logistics",
            company_registration_number="ZEPHYR-001",
            country="IN",
            currency="INR",
        )

        # Logged in as user 1
        resp_a = self.client.get(reverse("product_list"))
        self.assertContains(resp_a, "Apex Retail Corp")
        self.assertNotContains(resp_a, "Zephyr Logistics")

        # Log in as user 2
        self.client.force_login(other_user)
        resp_b = self.client.get(reverse("product_list"))
        self.assertContains(resp_b, "Zephyr Logistics")
        self.assertNotContains(resp_b, "Apex Retail Corp")

