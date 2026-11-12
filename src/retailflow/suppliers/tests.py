from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from company.context import get_current_tenant, reset_current_tenant, set_current_tenant
from company.models import Company
from employees.models import Employee
from products.models import Category, Product
from .forms import SupplierForm, SupplierProductForm
from .models import Supplier, SupplierProduct


class SupplierTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="supplier-owner@example.com", password="test-password", is_verified=True)
        cls.other_owner = User.objects.create_user(email="other-supplier-owner@example.com", password="test-password", is_verified=True)
        cls.company = Company.objects.create(user=cls.owner, company_name="Local company", company_registration_number="SUP-A")
        cls.other_company = Company.objects.create(user=cls.other_owner, company_name="Foreign company", company_registration_number="SUP-B")
        cls.supplier = Supplier.objects.create(company=cls.company, supplier_code="SUP-001", name="Local supplier")
        cls.foreign = Supplier.objects.create(company=cls.other_company, supplier_code="SUP-001", name="Private foreign supplier")
        category = Category.objects.create(company=cls.company, name="Local category")
        foreign_category = Category.objects.create(company=cls.other_company, name="Foreign category")
        cls.product = Product.objects.create(company=cls.company, category=category, name="Local product", sku="P1", purchase_price=10, selling_price=20)
        cls.foreign_product = Product.objects.create(company=cls.other_company, category=foreign_category, name="Private foreign product", sku="P1", purchase_price=10, selling_price=20)
        cls.link = SupplierProduct.objects.create(company=cls.company, supplier=cls.supplier, product=cls.product)
        cls.foreign_link = SupplierProduct.objects.create(company=cls.other_company, supplier=cls.foreign, product=cls.foreign_product)

    def setUp(self):
        self.client.force_login(self.owner)

    def supplier_data(self, **overrides):
        return {"supplier_code": "new-001", "name": "New supplier", "payment_terms_days": 30, "is_active": True, **overrides}

    def link_data(self, **overrides):
        return {"supplier": self.supplier.pk, "product": self.product.pk, "is_active": True, **overrides}

    def test_create_normalizes_code_and_ignores_company_and_timestamp(self):
        response = self.client.post(reverse("add_supplier"), self.supplier_data(company=self.other_company.pk, whatsapp_opt_in_at="2000-01-01"))
        supplier = Supplier.objects.get(company=self.company, supplier_code="NEW-001")
        self.assertRedirects(response, reverse("supplier_detail", args=[supplier.pk]))
        self.assertIsNone(supplier.whatsapp_opt_in_at)

    def test_edit_preserves_record_and_company(self):
        response = self.client.post(reverse("edit_supplier", args=[self.supplier.pk]), self.supplier_data(supplier_code="sup-001", company=self.other_company.pk))
        self.assertEqual(response.status_code, 302)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.name, "New supplier")
        self.assertEqual(self.supplier.company, self.company)
        self.assertTrue(SupplierProduct.objects.filter(pk=self.link.pk).exists())

    def test_duplicate_code_is_case_insensitive_and_tenant_scoped(self):
        Supplier.objects.filter(pk=self.supplier.pk).update(supplier_code="sUp-001")
        form = SupplierForm(self.supplier_data(supplier_code="SUP-001"), company=self.company)
        self.assertFalse(form.is_valid())
        self.assertIn("supplier_code", form.errors)
        form = SupplierForm(self.supplier_data(), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        form = SupplierForm(self.supplier_data(), company=self.other_company)
        self.assertTrue(form.is_valid(), form.errors)

    def test_gstin_and_whatsapp_validation(self):
        for values, field in [({"gstin": "invalid"}, "gstin"), ({"whatsapp_number": "919876543210"}, "whatsapp_number"), ({"whatsapp_opt_in": True}, "whatsapp_number"), ({"auto_stock_alerts_enabled": True}, "auto_stock_alerts_enabled")]:
            with self.subTest(values=values):
                form = SupplierForm(self.supplier_data(**values), company=self.company)
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)
        form = SupplierForm(self.supplier_data(gstin="27aapfu0939f1zv", whatsapp_number="+919876543210"), company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["gstin"], "27AAPFU0939F1ZV")

    def test_consent_grant_preservation_withdrawal_and_regrant(self):
        data = self.supplier_data(whatsapp_number="+919876543210", whatsapp_opt_in=True, auto_stock_alerts_enabled=True)
        form = SupplierForm(data, company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        supplier = form.save()
        timestamp = supplier.whatsapp_opt_in_at
        self.assertIsNotNone(timestamp)
        form = SupplierForm(data, instance=supplier, company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().whatsapp_opt_in_at, timestamp)
        form = SupplierForm({**data, "whatsapp_opt_in": False}, instance=supplier, company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        supplier = form.save()
        self.assertFalse(supplier.auto_stock_alerts_enabled)
        self.assertIsNone(supplier.whatsapp_opt_in_at)
        form = SupplierForm(data, instance=supplier, company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertGreaterEqual(form.save().whatsapp_opt_in_at, timestamp)

    def test_status_actions_are_post_only_and_preserve_links(self):
        for route, active in [("deactivate_supplier", False), ("activate_supplier", True)]:
            url = reverse(route, args=[self.supplier.pk])
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(self.client.post(url).status_code, 302)
            self.supplier.refresh_from_db()
            self.assertEqual(self.supplier.is_active, active)
            self.assertTrue(SupplierProduct.objects.filter(pk=self.link.pk).exists())

    def test_new_consent_replaces_stale_timestamp(self):
        old_timestamp = timezone.now() - timedelta(days=1)
        self.supplier.whatsapp_opt_in_at = old_timestamp
        self.supplier.save()
        form = SupplierForm(self.supplier_data(supplier_code="SUP-001", whatsapp_number="+919876543210", whatsapp_opt_in=True), instance=self.supplier, company=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertGreater(form.save().whatsapp_opt_in_at, old_timestamp)

    def test_details_display_zero_payment_terms(self):
        response = self.client.get(reverse("supplier_detail", args=[self.supplier.pk]))
        self.assertContains(response, "<dt>Payment terms days</dt><dd>0</dd>", html=True)

    def test_all_pages_use_shared_layout_and_active_navigation(self):
        for route, args in [("supplier_list", []), ("add_supplier", []), ("supplier_detail", [self.supplier.pk]), ("edit_supplier", [self.supplier.pk]), ("supplier_product_list", []), ("add_supplier_product", []), ("edit_supplier_product", [self.link.pk])]:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "layouts/admin_base.html")
                self.assertContains(response, 'id="sidebar"', count=1)
                self.assertContains(response, 'href="/suppliers/"\n       class="menu-item active"')
                self.assertNotContains(response, self.foreign.name)
                self.assertNotContains(response, self.foreign_product.name)
        for form in [SupplierForm(company=self.company), SupplierProductForm(company=self.company)]:
            self.assertNotIn("company", form.fields)
            self.assertNotIn("placeholder=", form.as_p())

    def test_search_status_and_pagination(self):
        for index in range(27):
            Supplier.objects.create(company=self.company, supplier_code=f"PAGE-{index}", name=f"Paged {index:02}", is_active=False)
        response = self.client.get(reverse("supplier_list"), {"q": "Paged", "status": "inactive", "page": 2})
        self.assertEqual(len(response.context["page_obj"]), 2)
        self.assertContains(response, "q=Paged&amp;status=inactive")
        self.assertNotContains(response, self.supplier.name)

    def test_foreign_supplier_get_and_post_are_rejected(self):
        for route in ["supplier_detail", "edit_supplier", "activate_supplier", "deactivate_supplier"]:
            url = reverse(route, args=[self.foreign.pk])
            if route in ["supplier_detail", "edit_supplier"]:
                self.assertEqual(self.client.get(url).status_code, 404)
            if route != "supplier_detail":
                self.assertEqual(self.client.post(url, self.supplier_data()).status_code, 404)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.name, "Private foreign supplier")
        self.assertTrue(self.foreign.is_active)

    def test_foreign_relationship_get_and_post_are_rejected(self):
        url = reverse("edit_supplier_product", args=[self.foreign_link.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, self.link_data()).status_code, 404)
        self.assertEqual(self.client.post(reverse("deactivate_supplier_product", args=[self.foreign_link.pk])).status_code, 404)

    def test_cross_company_choices_and_post_rejected(self):
        form = SupplierProductForm(company=self.company)
        self.assertNotIn(self.foreign, form.fields["supplier"].queryset)
        self.assertNotIn(self.foreign_product, form.fields["product"].queryset)
        for values, field in [({"supplier": self.foreign.pk}, "supplier"), ({"product": self.foreign_product.pk}, "product")]:
            response = self.client.post(reverse("add_supplier_product"), self.link_data(**values))
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context["form"].errors)
        with self.assertRaises(ValidationError):
            SupplierProduct(company=self.company, supplier=self.foreign, product=self.product).save()

    def test_assignment_edit_and_many_to_many(self):
        second = Supplier.objects.create(company=self.company, supplier_code="SECOND", name="Second")
        response = self.client.post(reverse("add_supplier_product"), self.link_data(supplier=second.pk, is_preferred=True, company=self.other_company.pk))
        self.assertRedirects(response, reverse("supplier_product_list"))
        link = SupplierProduct.objects.get(company=self.company, supplier=second)
        self.assertTrue(link.is_preferred)
        response = self.client.post(reverse("edit_supplier_product", args=[link.pk]), self.link_data(supplier=second.pk))
        self.assertEqual(response.status_code, 302)
        link.refresh_from_db()
        self.assertFalse(link.is_preferred)
        product = Product.objects.create(company=self.company, category=self.product.category, name="Second product", sku="P2", purchase_price=10, selling_price=20)
        self.assertEqual(self.client.post(reverse("add_supplier_product"), self.link_data(product=product.pk)).status_code, 302)

    def test_duplicate_relationship_and_preferred_uniqueness(self):
        form = SupplierProductForm(self.link_data(), company=self.company)
        self.assertFalse(form.is_valid())
        self.link.is_preferred = True
        self.link.save()
        second = Supplier.objects.create(company=self.company, supplier_code="SECOND", name="Second")
        form = SupplierProductForm(self.link_data(supplier=second.pk, is_preferred=True), company=self.company)
        self.assertFalse(form.is_valid())
        self.assertIn("is_preferred", form.errors)
        # The existing partial database constraint also guards non-form writes.
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupplierProduct.objects.bulk_create([SupplierProduct(company=self.company, supplier=second, product=self.product, is_preferred=True)])

    def test_deactivate_link_clears_preference_and_can_reactivate(self):
        self.link.is_preferred = True
        self.link.save()
        url = reverse("deactivate_supplier_product", args=[self.link.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.link.refresh_from_db()
        self.assertFalse(self.link.is_active)
        self.assertFalse(self.link.is_preferred)
        self.assertEqual(self.client.post(reverse("edit_supplier_product", args=[self.link.pk]), self.link_data()).status_code, 302)
        self.link.refresh_from_db()
        self.assertTrue(self.link.is_active)

    def test_unauthorized_accounts(self):
        employee = User.objects.create_user(email="supplier-employee@example.com", password="test-password", is_verified=True)
        Employee.objects.create(company=self.company, user=employee, role="MANAGER")
        unattached = User.objects.create_user(email="unattached@example.com", password="test-password", is_verified=True)
        routes = [("supplier_list", []), ("add_supplier", []), ("supplier_detail", [self.supplier.pk]), ("edit_supplier", [self.supplier.pk]), ("supplier_product_list", []), ("add_supplier_product", []), ("edit_supplier_product", [self.link.pk]), ("deactivate_supplier", [self.supplier.pk]), ("activate_supplier", [self.supplier.pk]), ("deactivate_supplier_product", [self.link.pk])]
        for user in [employee, unattached]:
            self.client.force_login(user)
            for route, args in routes:
                url = reverse(route, args=args)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.logout()
        for route, args in routes:
            self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 302)

    def test_csrf_required_for_every_write_route(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for route, args in [("add_supplier", []), ("edit_supplier", [self.supplier.pk]), ("activate_supplier", [self.supplier.pk]), ("deactivate_supplier", [self.supplier.pk]), ("add_supplier_product", []), ("edit_supplier_product", [self.link.pk]), ("deactivate_supplier_product", [self.link.pk])]:
            self.assertEqual(client.post(reverse(route, args=args), {}).status_code, 403)
        client.get(reverse("add_supplier"))
        response = client.post(reverse("add_supplier"), self.supplier_data(), HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 302)

    def test_form_context_and_foreign_instance_guard(self):
        token = set_current_tenant(self.company)
        try:
            self.assertEqual(SupplierForm().instance.company, self.company)
            with self.assertRaises(PermissionDenied):
                SupplierForm(instance=self.foreign)
            with self.assertRaises(PermissionDenied):
                SupplierProductForm(instance=self.foreign_link)
        finally:
            reset_current_tenant(token)
        self.assertIsNone(get_current_tenant())
        with self.assertRaises(PermissionDenied):
            SupplierForm()


    def test_supplier_popup_rendering(self):
        """Floating popup window rendering with minimal layout and quick product search."""
        for url in [
            reverse("add_supplier") + "?popup=1",
            reverse("edit_supplier", args=[self.supplier.pk]) + "?popup=1",
            reverse("supplier_detail", args=[self.supplier.pk]) + "?popup=1",
            reverse("add_supplier_product") + "?popup=1",
        ]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertTemplateUsed(resp, "layouts/popup_base.html")
            self.assertNotContains(resp, 'id="sidebar"')
            self.assertNotContains(resp, 'class="topbar"')

        # Check product search filter on product link popup
        link_resp = self.client.get(reverse("add_supplier_product") + "?popup=1")
        self.assertContains(link_resp, 'id="rf-prod-filter"')

    def test_supplier_popup_ajax_crud(self):
        """AJAX form submissions inside popup windows return JSON and update database."""
        # Add supplier via AJAX popup
        new_data = self.supplier_data(supplier_code="POP-SUP", name="Popup Supplier")
        resp = self.client.post(
            reverse("add_supplier"),
            new_data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.json()
        self.assertTrue(json_data.get("success"))
        created = Supplier.objects.get(supplier_code="POP-SUP", company=self.company)
        self.assertEqual(created.name, "Popup Supplier")

        # Edit supplier via AJAX popup
        edit_data = self.supplier_data(name="Updated Popup Supplier")
        resp = self.client.post(
            reverse("edit_supplier", args=[created.pk]),
            edit_data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        created.refresh_from_db()
        self.assertEqual(created.name, "Updated Popup Supplier")

        # Deactivate via AJAX popup
        resp = self.client.post(
            reverse("deactivate_supplier", args=[created.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        created.refresh_from_db()
        self.assertFalse(created.is_active)

        # Activate via AJAX popup
        resp = self.client.post(
            reverse("activate_supplier", args=[created.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        created.refresh_from_db()
        self.assertTrue(created.is_active)

        # Deactivate product link via AJAX popup
        resp = self.client.post(
            reverse("deactivate_supplier_product", args=[self.link.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        self.link.refresh_from_db()
        self.assertFalse(self.link.is_active)

    def test_supplier_popup_ajax_validation_error(self):
        """Invalid AJAX submission inside popup re-renders form errors without saving."""
        count = Supplier.objects.filter(company=self.company).count()
        resp = self.client.post(
            reverse("add_supplier") + "?popup=1",
            {"supplier_code": "", "name": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Please correct the errors below")
        self.assertEqual(Supplier.objects.filter(company=self.company).count(), count)
