from decimal import Decimal
import uuid
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections, close_old_connections, IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from company.models import Company
from employees.models import Employee
from products.models import Category, Product
from suppliers.models import Supplier, SupplierProduct
from inventory.models import Inventory, StockMovement
from . import services
from .models import PurchaseOrder, PurchaseOrderItem, GoodsReceipt, PurchaseInvoice, PurchaseInvoiceItem, PurchasePayment


class PurchaseFixtures:
    def make_data(self):
        self.user = User.objects.create_user(email="purchaser@example.com", password="test", is_verified=True)
        self.other_user = User.objects.create_user(email="other-purchaser@example.com", password="test", is_verified=True)
        self.company = Company.objects.create(user=self.user, company_name="Purchaser", company_registration_number="PUR-A", currency="INR")
        self.other = Company.objects.create(user=self.other_user, company_name="Other", company_registration_number="PUR-B", currency="INR")
        self.supplier = Supplier.objects.create(company=self.company, name="Supplier", supplier_code="SUP")
        self.foreign_supplier = Supplier.objects.create(company=self.other, name="Private supplier", supplier_code="SUP")
        category = Category.objects.create(company=self.company, name="Goods")
        foreign_category = Category.objects.create(company=self.other, name="Other goods")
        self.product = Product.objects.create(company=self.company, category=category, name="Product", sku="SKU", purchase_price=10, selling_price=20)
        self.foreign_product = Product.objects.create(company=self.other, category=foreign_category, name="Private product", sku="SKU", purchase_price=10, selling_price=20)

    def order_data(self, **kwargs):
        return {"supplier": self.supplier, "order_date": timezone.localdate(), "expected_delivery_date": None, "notes": "", **kwargs}

    def line_data(self, **kwargs):
        return {"product": self.product, "quantity": 50, "unit_cost": Decimal("10.00"), "discount_percent": Decimal("0"), "tax_percent": Decimal("0"), **kwargs}

    def create_order(self, **kwargs):
        return services.save_order(company=self.company, user=self.user, data=self.order_data(), lines=[self.line_data()], **kwargs)

    def post_data(self):
        return {"supplier": self.supplier.pk, "order_date": str(timezone.localdate()), "notes": "", "items-TOTAL_FORMS": 1, "items-INITIAL_FORMS": 0, "items-0-product": self.product.pk, "items-0-quantity": 50, "items-0-unit_cost": "10.00", "items-0-discount_percent": 0, "items-0-tax_percent": 0}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OrderTests(PurchaseFixtures, TestCase):
    def setUp(self):
        self.make_data()
        self.client.force_login(self.user)

    def test_numbering_and_company_scope(self):
        self.assertEqual(self.create_order().number, "PO-0001")
        self.assertEqual(self.create_order().number, "PO-0002")
        order = services.save_order(company=self.other, user=self.other_user, data=self.order_data(supplier=self.foreign_supplier), lines=[self.line_data(product=self.foreign_product)])
        self.assertEqual(order.number, "PO-0001")
        self.assertEqual(self.client.get(reverse("purchase_order_detail", args=[order.pk])).status_code, 404)

    def test_form_create_edit_and_render(self):
        response = self.client.post(reverse("add_purchase_order"), self.post_data())
        order = PurchaseOrder.objects.get(company=self.company)
        self.assertRedirects(response, reverse("purchase_order_detail", args=[order.pk]))
        data = self.post_data()
        data["items-0-quantity"] = 25
        self.assertEqual(self.client.post(reverse("edit_purchase_order", args=[order.pk]), data).status_code, 302)
        self.assertEqual(order.items.get().quantity, 25)
        for name, args in [("purchase_order_list", []), ("add_purchase_order", []), ("edit_purchase_order", [order.pk]), ("purchase_order_detail", [order.pk])]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, "layouts/admin_base.html")

    def test_amounts_and_item_validation(self):
        order = services.save_order(company=self.company, user=self.user, data=self.order_data(), lines=[self.line_data(quantity=3, unit_cost=Decimal("10.05"), discount_percent=Decimal("10"), tax_percent=Decimal("5"))])
        self.assertEqual(order.totals["line_total"], Decimal("28.49"))
        for changes in [{"quantity": 0}, {"unit_cost": Decimal("-1")}, {"product": self.foreign_product}]:
            with self.assertRaises(ValidationError):
                services.save_order(company=self.company, user=self.user, data=self.order_data(), lines=[self.line_data(**changes)])
        with self.assertRaises(ValidationError):
            services.save_order(company=self.company, user=self.user, data=self.order_data(supplier=self.foreign_supplier), lines=[self.line_data()])

    def test_transitions_and_historical_costs(self):
        order = self.create_order()
        services.transition_order(company=self.company, user=self.user, pk=order.pk, action="place")
        for action in ["place", "unknown"]:
            with self.assertRaises(ValidationError):
                services.transition_order(company=self.company, user=self.user, pk=order.pk, action=action)
        with self.assertRaises(ValidationError):
            self.create_order(pk=order.pk)
        self.product.purchase_price = 99
        self.product.save()
        self.assertEqual(order.items.get().unit_cost, Decimal("10"))
        self.assertEqual(self.product.selling_price, 20)
        services.transition_order(company=self.company, user=self.user, pk=order.pk, action="cancel")

    def test_duplicate_lines_and_supplier_catalogue(self):
        with self.assertRaises(ValidationError):
            services.save_order(company=self.company, user=self.user, data=self.order_data(), lines=[self.line_data(), self.line_data()])
        SupplierProduct.objects.create(company=self.company, supplier=self.supplier, product=self.product, is_active=False)
        with self.assertRaises(ValidationError):
            self.create_order()

    def test_cross_company_form_rejected(self):
        for field, value in [("supplier", self.foreign_supplier.pk), ("items-0-product", self.foreign_product.pk)]:
            data = self.post_data()
            data[field] = value
            self.assertEqual(self.client.post(reverse("add_purchase_order"), data).status_code, 200)
            self.assertFalse(PurchaseOrder.objects.exists())

    def test_search_date_status_and_pagination(self):
        for unused in range(26):
            self.create_order()
        response = self.client.get(reverse("purchase_order_list"), {"q": "Supplier", "status": "DRAFT", "from": str(timezone.localdate()), "to": str(timezone.localdate()), "page": 2})
        self.assertEqual(len(response.context["page_obj"]), 1)
        self.assertContains(response, "status=DRAFT")
        self.assertEqual(self.client.get(reverse("purchase_order_list"), {"from": "2026-99-99"}).status_code, 200)
        response = self.client.get(reverse("purchase_order_list"), {"status": "ORDERED"})
        self.assertEqual(response.context["page_obj"].paginator.count, 0)


class ReceiptFixtures(PurchaseFixtures):
    def placed_order(self):
        order = self.create_order()
        return services.transition_order(company=self.company, user=self.user, pk=order.pk, action="place")

    def receipt(self, order, accepted=30, damaged=0, rejected=0):
        return services.save_receipt(company=self.company, user=self.user, order_pk=order.pk, data={"receipt_date": timezone.localdate(), "delivery_reference": "Delivery", "notes": ""}, lines=[{"order_item": order.items.get(), "accepted_quantity": accepted, "damaged_quantity": damaged, "rejected_quantity": rejected, "notes": ""}])

    def confirm(self, receipt):
        return services.confirm_receipt(company=self.company, user=self.user, pk=receipt.pk)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ReceiptTests(ReceiptFixtures, TestCase):
    def setUp(self):
        self.make_data()
        self.client.force_login(self.user)

    def test_partial_full_and_duplicate_confirmation(self):
        order = self.placed_order()
        receipt = self.receipt(order)
        self.assertFalse(Inventory.objects.exists())
        self.confirm(receipt)
        self.confirm(receipt)
        self.assertEqual(Inventory.objects.get(company=self.company).quantity, 30)
        self.assertEqual(StockMovement.objects.count(), 1)
        order.refresh_from_db()
        self.assertEqual(order.status, "PARTIALLY_RECEIVED")
        self.confirm(self.receipt(order, accepted=20))
        order.refresh_from_db()
        self.assertEqual(order.status, "RECEIVED")
        self.assertEqual(Inventory.objects.get(company=self.company).quantity, 50)
        response = self.client.get(reverse("product_list"))
        self.assertEqual(response.context["products"][0].available_stock, 50)
        self.assertEqual(list(StockMovement.objects.values_list("movement_type", flat=True)), ["IN", "IN"])

    def test_over_receiving_and_stale_drafts(self):
        order = self.placed_order()
        with self.assertRaises(ValidationError):
            self.receipt(order, accepted=51)
        first, stale = self.receipt(order, accepted=30), self.receipt(order, accepted=30)
        self.confirm(first)
        with self.assertRaises(ValidationError):
            self.confirm(stale)
        self.assertEqual(Inventory.objects.get().quantity, 30)

    def test_returned_damage_and_rejection_are_not_stock(self):
        order = self.placed_order()
        self.confirm(self.receipt(order, accepted=30, damaged=10, rejected=10))
        inventory = Inventory.objects.get()
        self.assertEqual((inventory.quantity, inventory.damaged_quantity), (30, 0))
        self.assertEqual(order.items.get().remaining_quantity, 20)

    def test_confirmation_rollback(self):
        order = self.placed_order()
        receipt = self.receipt(order)
        real_save = GoodsReceipt.save
        def fail_confirm(instance, *args, **kwargs):
            if instance.status == "CONFIRMED":
                raise ValidationError("Simulated failure after stock update")
            return real_save(instance, *args, **kwargs)
        with patch.object(GoodsReceipt, "save", fail_confirm), self.assertRaises(ValidationError):
            self.confirm(receipt)
        self.assertFalse(Inventory.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "DRAFT")

    def test_confirmed_immutable_and_cannot_cancel(self):
        order = self.placed_order()
        receipt = self.confirm(self.receipt(order))
        with self.assertRaises(ValidationError):
            receipt.save()
        line = receipt.items.get()
        line.accepted_quantity = 1
        with self.assertRaises(ValidationError):
            line.save()
        with self.assertRaises(ValidationError):
            services.transition_order(company=self.company, user=self.user, pk=order.pk, action="cancel")

    def test_receipt_forms_and_pages(self):
        order = self.placed_order()
        data = {"receipt_date": str(timezone.localdate()), "delivery_reference": "D1", "items-TOTAL_FORMS": 1, "items-INITIAL_FORMS": 1, "items-0-order_item": order.items.get().pk, "items-0-accepted_quantity": 20, "items-0-damaged_quantity": 2, "items-0-rejected_quantity": 3}
        response = self.client.post(reverse("add_goods_receipt", args=[order.pk]), data)
        receipt = GoodsReceipt.objects.get()
        self.assertRedirects(response, reverse("goods_receipt_detail", args=[receipt.pk]))
        for name, args in [("goods_receipt_list", []), ("goods_receipt_detail", [receipt.pk]), ("edit_goods_receipt", [order.pk, receipt.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        self.assertEqual(self.client.get(reverse("confirm_goods_receipt", args=[receipt.pk])).status_code, 405)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class InvoiceTests(ReceiptFixtures, TestCase):
    def setUp(self):
        self.make_data()
        self.client.force_login(self.user)

    def test_auto_invoice_and_partial_totals(self):
        order = self.placed_order()
        first = self.confirm(self.receipt(order))
        self.confirm(first)
        second = self.confirm(self.receipt(order, accepted=20))
        self.assertEqual(PurchaseInvoice.objects.count(), 2)
        self.assertEqual(first.invoice.number, "PINV-0001")
        self.assertEqual(second.invoice.number, "PINV-0002")
        self.assertEqual(first.invoice.grand_total, Decimal("300"))
        self.assertEqual(second.invoice.grand_total, Decimal("200"))
        self.assertEqual(first.invoice.status, "PENDING")
        self.assertEqual(first.invoice.supplier_invoice_number, "")

    def test_partial_rounding_matches_order(self):
        order = services.save_order(company=self.company, user=self.user, data=self.order_data(), lines=[self.line_data(quantity=3, unit_cost=Decimal("0.05"), discount_percent=Decimal("10"), tax_percent=Decimal("5"))])
        services.transition_order(company=self.company, user=self.user, pk=order.pk, action="place")
        for unused in range(3):
            self.confirm(self.receipt(order, accepted=1))
        self.assertEqual(sum(PurchaseInvoice.objects.values_list("grand_total", flat=True)), order.totals["line_total"])

    def test_reconcile_and_immutable_snapshots(self):
        invoice = self.confirm(self.receipt(self.placed_order())).invoice
        self.supplier.name = "Changed supplier"
        self.supplier.save()
        self.product.name = "Changed product"
        self.product.save()
        self.assertEqual(invoice.supplier_snapshot["name"], "Supplier")
        self.assertEqual(invoice.items.get().product_name, "Product")
        data = {"supplier_invoice_number": "REAL-2026", "invoice_date": str(timezone.localdate()), "tax_amount": "12.25", "additional_charges": "5.00", "notes": "Matched", "verified": "on"}
        response = self.client.post(reverse("reconcile_purchase_invoice", args=[invoice.pk]), data)
        self.assertRedirects(response, reverse("purchase_invoice_detail", args=[invoice.pk]))
        invoice.refresh_from_db()
        self.assertEqual(invoice.grand_total, Decimal("317.25"))
        with self.assertRaises(ValidationError):
            invoice.save()
        with self.assertRaises(ValidationError):
            invoice.items.get().save()
        for route, args in [("purchase_invoice_list", []), ("purchase_invoice_detail", [invoice.pk])]:
            self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 200)

    def test_invoice_failure_rolls_back_receiving(self):
        receipt = self.receipt(self.placed_order())
        with patch("purchases.services.create_receipt_invoice", side_effect=ValidationError("Invoice failure")), self.assertRaises(ValidationError):
            self.confirm(receipt)
        self.assertFalse(Inventory.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(PurchaseInvoice.objects.exists())
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "DRAFT")

    def test_returned_only_receipt_has_no_invoice(self):
        receipt = self.confirm(self.receipt(self.placed_order(), accepted=0, rejected=10))
        self.assertFalse(PurchaseInvoice.objects.exists())
        self.assertFalse(Inventory.objects.exists())
        self.assertEqual(receipt.order.status, "ORDERED")


class PaymentFixtures(ReceiptFixtures):
    def verified_invoice(self):
        invoice = self.confirm(self.receipt(self.placed_order())).invoice
        return services.reconcile_invoice(company=self.company, user=self.user, pk=invoice.pk, data={"supplier_invoice_number": "BILL-1", "invoice_date": timezone.localdate(), "tax_amount": Decimal("0"), "additional_charges": Decimal("0"), "notes": "", "verified": True})

    def payment_data(self, **kwargs):
        return {"payment_date": timezone.localdate(), "amount": Decimal("100"), "method": "BANK", "reference": "", "notes": "", "request_key": uuid.uuid4(), **kwargs}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PaymentTests(PaymentFixtures, TestCase):
    def setUp(self):
        self.make_data()
        self.client.force_login(self.user)

    def test_partial_full_overpayment_and_duplicate(self):
        invoice = self.verified_invoice()
        self.assertEqual(invoice.payment_status, "Unpaid")
        data = self.payment_data()
        first = services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=data)
        retry = services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=data)
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(invoice.outstanding, Decimal("200"))
        self.assertEqual(invoice.payment_status, "Partially paid")
        with self.assertRaises(ValidationError):
            services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=self.payment_data(amount=Decimal("201")))
        services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=self.payment_data(amount=Decimal("200")))
        self.assertEqual(invoice.outstanding, Decimal("0"))
        self.assertEqual(invoice.payment_status, "Paid")
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_full_payment_redirect_preserves_receiving_and_stock(self):
        invoice = self.verified_invoice()
        inventory = Inventory.objects.get(company=self.company, product=self.product)
        original_stock = (inventory.quantity, inventory.damaged_quantity)
        original_order_status = invoice.order.status
        original_receipt_status = invoice.receipt.status
        response = self.client.post(
            reverse("add_purchase_payment", args=[invoice.pk]),
            self.payment_data(amount=invoice.outstanding), follow=True,
        )
        self.assertRedirects(response, reverse("purchase_order_list"))
        self.assertContains(response, f"Payment completed successfully for {invoice.order.number}. The purchase is fully paid.")
        self.assertEqual(invoice.outstanding, Decimal("0.00"))
        self.assertEqual(invoice.payments.count(), 1)
        inventory.refresh_from_db()
        invoice.order.refresh_from_db()
        invoice.receipt.refresh_from_db()
        self.assertEqual((inventory.quantity, inventory.damaged_quantity), original_stock)
        self.assertEqual(invoice.order.status, original_order_status)
        self.assertEqual(invoice.receipt.status, original_receipt_status)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(PurchaseInvoice.objects.count(), 1)

    def test_partial_then_final_payment_redirects(self):
        invoice = self.verified_invoice()
        url = reverse("add_purchase_payment", args=[invoice.pk])
        response = self.client.post(url, self.payment_data(), follow=True)
        self.assertRedirects(response, reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertContains(response, "Payment recorded. A balance of INR 200.00 remains.")
        self.assertEqual(invoice.outstanding, Decimal("200.00"))
        response = self.client.post(url, self.payment_data(amount=Decimal("200.00")))
        self.assertRedirects(response, reverse("purchase_order_list"))
        self.assertEqual(invoice.outstanding, Decimal("0.00"))
        self.assertEqual(invoice.paid_amount, Decimal("300.00"))
        self.assertEqual(invoice.payments.count(), 2)

    def test_invalid_payment_does_not_redirect_or_save(self):
        invoice = self.verified_invoice()
        url = reverse("add_purchase_payment", args=[invoice.pk])
        for amount in ("301.00", "0", "-1", "invalid"):
            with self.subTest(amount=amount):
                response = self.client.post(url, self.payment_data(amount=amount))
                self.assertEqual(response.status_code, 200)
                self.assertIn("amount", response.context["form"].errors)
                self.assertFalse(invoice.payments.exists())
                self.assertEqual(invoice.outstanding, Decimal("300.00"))

    def test_pending_zero_negative_and_immutable_payment(self):
        pending = self.confirm(self.receipt(self.placed_order())).invoice
        with self.assertRaises(ValidationError):
            services.record_payment(company=self.company, user=self.user, invoice_pk=pending.pk, data=self.payment_data())
        invoice = self.verified_invoice()
        for amount in [Decimal("0"), Decimal("-1")]:
            with self.assertRaises(ValidationError):
                services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=self.payment_data(amount=amount))
        payment = services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=self.payment_data())
        with self.assertRaises(ValidationError):
            payment.save()

    def test_payment_http_retry_and_reference_guard(self):
        invoice = self.verified_invoice()
        data = self.payment_data(reference="BANK-123")
        url = reverse("add_purchase_payment", args=[invoice.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        for unused in range(2):
            self.assertRedirects(self.client.post(url, data), reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertEqual(PurchasePayment.objects.count(), 1)
        data["request_key"] = uuid.uuid4()
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertEqual(PurchasePayment.objects.count(), 1)
        self.assertEqual(self.client.get(reverse("purchase_payment_list")).status_code, 200)

    def test_complete_http_workflow_with_multiple_products(self):
        second = Product.objects.create(company=self.company, category=self.product.category, name="Second", sku="SECOND", purchase_price=5, selling_price=9)
        data = self.post_data()
        data.update({"items-TOTAL_FORMS": 2, "items-1-product": second.pk, "items-1-quantity": 10, "items-1-unit_cost": "5.00", "items-1-discount_percent": 0, "items-1-tax_percent": 0})
        self.assertEqual(self.client.post(reverse("add_purchase_order"), data).status_code, 302)
        order = PurchaseOrder.objects.get()
        self.assertEqual(self.client.post(reverse("place_purchase_order", args=[order.pk])).status_code, 302)
        lines = list(order.items.order_by("pk"))
        receipt_data = {"receipt_date": str(timezone.localdate()), "items-TOTAL_FORMS": 2, "items-INITIAL_FORMS": 2}
        for index, line in enumerate(lines):
            receipt_data.update({f"items-{index}-order_item": line.pk, f"items-{index}-accepted_quantity": line.quantity if index == 0 else 0, f"items-{index}-damaged_quantity": 0, f"items-{index}-rejected_quantity": 0})
        self.assertEqual(self.client.post(reverse("add_goods_receipt", args=[order.pk]), receipt_data).status_code, 302)
        receipt = GoodsReceipt.objects.get()
        self.assertEqual(receipt.items.count(), 1)
        self.assertFalse(Inventory.objects.exists())
        self.assertEqual(self.client.post(reverse("confirm_goods_receipt", args=[receipt.pk])).status_code, 302)
        invoice = PurchaseInvoice.objects.get()
        self.assertEqual(invoice.grand_total, Decimal("500"))
        reconciliation = {"supplier_invoice_number": "ACTUAL-1", "invoice_date": str(timezone.localdate()), "tax_amount": "0", "additional_charges": "0", "verified": "on"}
        self.assertEqual(self.client.post(reverse("reconcile_purchase_invoice", args=[invoice.pk]), reconciliation).status_code, 302)
        self.assertEqual(self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), self.payment_data(amount=Decimal("500"))).status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.payment_status, "Paid")
        order.refresh_from_db()
        self.assertEqual(order.status, "PARTIALLY_RECEIVED")
        products = {product.pk: product.available_stock for product in self.client.get(reverse("product_list")).context["products"]}
        self.assertEqual(products[self.product.pk], 50)
        self.assertIsNone(products[second.pk])


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SecurityTests(PaymentFixtures, TestCase):
    def setUp(self):
        self.make_data()
        self.invoice = self.verified_invoice()
        self.order = self.invoice.order
        self.received = self.invoice.receipt
        self.draft = self.create_order()
        self.open_order = self.placed_order()
        self.draft_receipt = self.receipt(self.open_order)
        self.pending = self.confirm(self.receipt(self.open_order, accepted=10)).invoice
        self.client.force_login(self.user)

    def get_routes(self):
        return [("purchase_order_list", []), ("add_purchase_order", []), ("purchase_order_detail", [self.order.pk]), ("edit_purchase_order", [self.draft.pk]), ("goods_receipt_list", []), ("goods_receipt_detail", [self.received.pk]), ("add_goods_receipt", [self.open_order.pk]), ("edit_goods_receipt", [self.open_order.pk, self.draft_receipt.pk]), ("purchase_invoice_list", []), ("purchase_invoice_detail", [self.invoice.pk]), ("reconcile_purchase_invoice", [self.pending.pk]), ("add_purchase_payment", [self.invoice.pk]), ("purchase_payment_list", [])]

    def write_routes(self):
        return [("add_purchase_order", []), ("edit_purchase_order", [self.draft.pk]), ("place_purchase_order", [self.draft.pk]), ("cancel_purchase_order", [self.draft.pk]), ("add_goods_receipt", [self.open_order.pk]), ("edit_goods_receipt", [self.open_order.pk, self.draft_receipt.pk]), ("confirm_goods_receipt", [self.draft_receipt.pk]), ("reconcile_purchase_invoice", [self.pending.pk]), ("add_purchase_payment", [self.invoice.pk])]

    def test_foreign_urls_and_lists(self):
        self.client.force_login(self.other_user)
        for route, args in self.get_routes():
            response = self.client.get(reverse(route, args=args))
            if args:
                self.assertEqual(response.status_code, 404, route)
            else:
                self.assertEqual(response.status_code, 200, route)
                self.assertNotContains(response, self.supplier.name + "</td>")
                if "page_obj" in response.context:
                    self.assertEqual(response.context["page_obj"].paginator.count, 0)
        for route, args in self.write_routes():
            if args:
                self.assertEqual(self.client.post(reverse(route, args=args), {}).status_code, 404, route)
        self.assertFalse(Inventory.objects.filter(company=self.other).exists())

    def test_unauthorized_all_routes(self):
        employee = User.objects.create_user(email="purchase-employee@example.com", password="test", is_verified=True)
        Employee.objects.create(company=self.company, user=employee, role="MANAGER")
        unattached = User.objects.create_user(email="purchase-unattached@example.com", password="test", is_verified=True)
        for user in (employee, unattached):
            self.client.force_login(user)
            for route, args in self.get_routes():
                self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 403, route)
            for route, args in self.write_routes():
                self.assertEqual(self.client.post(reverse(route, args=args), {}).status_code, 403, route)
        with self.assertRaises(PermissionDenied):
            services.confirm_receipt(company=self.company, user=employee, pk=self.draft_receipt.pk)
        self.client.logout()
        for route, args in self.get_routes():
            self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 302)

    def test_csrf_and_post_only_actions(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for route, args in self.write_routes():
            self.assertEqual(client.post(reverse(route, args=args), {}).status_code, 403, route)
        for route, args in [("place_purchase_order", [self.draft.pk]), ("cancel_purchase_order", [self.draft.pk]), ("confirm_goods_receipt", [self.draft_receipt.pk])]:
            self.assertEqual(client.get(reverse(route, args=args)).status_code, 405)
        client.get(reverse("add_purchase_order"))
        self.assertEqual(client.post(reverse("add_purchase_order"), self.post_data(), HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value).status_code, 302)

    def test_layout_navigation_and_no_form_placeholders(self):
        for route, args in self.get_routes():
            response = self.client.get(reverse(route, args=args))
            self.assertEqual(response.status_code, 200, route)
            self.assertTemplateUsed(response, "layouts/admin_base.html")
            self.assertContains(response, 'id="sidebar"', count=1)
            self.assertContains(response, 'href="/purchases/"\n       class="menu-item active"')
            if response.context.get("form"):
                self.assertNotIn("placeholder=", response.context["form"].as_p())
                self.assertNotIn("company", response.context["form"].fields)

    def test_other_order_item_rejected(self):
        data = {"receipt_date": str(timezone.localdate()), "items-TOTAL_FORMS": 1, "items-INITIAL_FORMS": 1, "items-0-order_item": self.order.items.get().pk, "items-0-accepted_quantity": 1, "items-0-damaged_quantity": 0, "items-0-rejected_quantity": 0}
        response = self.client.post(reverse("add_goods_receipt", args=[self.open_order.pk]), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("order_item", response.context["formset"].forms[0].errors)

    def test_forged_company_and_payment_token_payload(self):
        data = self.post_data()
        data["company"] = self.other.pk
        self.client.post(reverse("add_purchase_order"), data)
        self.assertFalse(PurchaseOrder.objects.filter(company=self.other).exists())
        payment_data = self.payment_data()
        services.record_payment(company=self.company, user=self.user, invoice_pk=self.invoice.pk, data=payment_data)
        with self.assertRaises(ValidationError):
            services.record_payment(company=self.company, user=self.user, invoice_pk=self.invoice.pk, data={**payment_data, "amount": Decimal("2")})

    def test_database_duplicate_guards_and_stale_models(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PurchaseOrder.objects.bulk_create([PurchaseOrder(company=self.company, supplier=self.supplier, number=self.order.number, created_by=self.user)])
        stale_line = self.draft.items.get()
        stale_line.order = self.draft
        placed = services.transition_order(company=self.company, user=self.user, pk=self.draft.pk, action="place")
        with self.assertRaises(ValidationError):
            stale_line.save()
        placed.notes = "Accidental historical change"
        with self.assertRaises(ValidationError):
            placed.save()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
@skipUnlessDBFeature("has_select_for_update")
class ConcurrencyTests(PaymentFixtures, TransactionTestCase):
    def setUp(self):
        self.make_data()

    def run_concurrently(self, operations):
        barrier = Barrier(2)
        def run(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return operation()
                except ValidationError:
                    return "rejected"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=30) for future in futures]

    def test_concurrent_number_allocation(self):
        results = self.run_concurrently([lambda: self.create_order().number, lambda: self.create_order().number])
        self.assertEqual(set(results), {"PO-0001", "PO-0002"})

    def test_concurrent_same_receipt_confirmation(self):
        receipt = self.receipt(self.placed_order())
        results = self.run_concurrently([lambda: self.confirm(receipt).pk, lambda: self.confirm(receipt).pk])
        self.assertEqual(results, [receipt.pk, receipt.pk])
        self.assertEqual(Inventory.objects.get().quantity, 30)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(PurchaseInvoice.objects.count(), 1)

    def test_concurrent_receipts_cannot_over_receive(self):
        order = self.placed_order()
        first, second = self.receipt(order), self.receipt(order)
        results = self.run_concurrently([lambda: self.confirm(first).pk, lambda: self.confirm(second).pk])
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(Inventory.objects.get().quantity, 30)

    def test_concurrent_payment_retry(self):
        invoice = self.verified_invoice()
        data = self.payment_data()
        def pay():
            return services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=data).pk
        results = self.run_concurrently([pay, pay])
        self.assertEqual(results[0], results[1])
        self.assertEqual(PurchasePayment.objects.count(), 1)

    def test_concurrent_payments_cannot_overpay(self):
        invoice = self.verified_invoice()
        def pay():
            return services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=self.payment_data(amount=Decimal("200"))).pk
        results = self.run_concurrently([pay, pay])
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(invoice.outstanding, Decimal("100"))



@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class NavigationAndRepeatedActionTests(PaymentFixtures, TestCase):
    def setUp(self):
        self.make_data()
        self.client.force_login(self.user)

    def test_cache_control_headers_prevent_browser_caching(self):
        """1. Targeted Cache-Control no-store headers on purchase views."""
        order = self.placed_order()
        receipt = self.receipt(order)
        invoice = self.confirm(receipt).invoice
        routes = [
            ("purchase_order_list", []),
            ("add_purchase_order", []),
            ("purchase_order_detail", [order.pk]),
            ("edit_purchase_order", [self.create_order().pk]),
            ("goods_receipt_list", []),
            ("add_goods_receipt", [order.pk]),
            ("goods_receipt_detail", [receipt.pk]),
            ("purchase_invoice_list", []),
            ("purchase_invoice_detail", [invoice.pk]),
            ("reconcile_purchase_invoice", [invoice.pk]),
            ("add_purchase_payment", [invoice.pk]),
        ]
        for name, args in routes:
            response = self.client.get(reverse(name, args=args))
            cache_control = response.headers.get("Cache-Control", "")
            self.assertIn("no-store", cache_control, f"{name} must have no-store")
            self.assertIn("no-cache", cache_control, f"{name} must have no-cache")
            self.assertIn("must-revalidate", cache_control, f"{name} must have must-revalidate")

    def test_stale_back_navigation_redirects_safely(self):
        """1. Browser navigation returning to previously completed document pages."""
        # A placed order should reject GET to edit form and redirect with an error message
        order = self.placed_order()
        response = self.client.get(reverse("edit_purchase_order", args=[order.pk]), follow=True)
        self.assertRedirects(response, reverse("purchase_order_detail", args=[order.pk]))
        self.assertContains(response, "Only draft orders can be edited.")

        # A confirmed receipt should reject GET to edit form and redirect
        receipt = self.confirm(self.receipt(order))
        response = self.client.get(reverse("edit_goods_receipt", args=[order.pk, receipt.pk]), follow=True)
        self.assertRedirects(response, reverse("goods_receipt_detail", args=[receipt.pk]))
        self.assertContains(response, "Confirmed receipts cannot be edited.")

        # A verified invoice should reject GET to reconcile form and redirect
        invoice = receipt.invoice
        services.reconcile_invoice(
            company=self.company, user=self.user, pk=invoice.pk,
            data={"supplier_invoice_number": "BILL-100", "invoice_date": timezone.localdate(), "tax_amount": Decimal("0"), "additional_charges": Decimal("0"), "notes": "", "verified": True}
        )
        response = self.client.get(reverse("reconcile_purchase_invoice", args=[invoice.pk]), follow=True)
        self.assertRedirects(response, reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertContains(response, "This invoice is already verified and cannot be changed.")

        # Fully pay invoice
        services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=self.payment_data(amount=invoice.outstanding))
        # A fully paid invoice should reject GET to payment form and redirect
        response = self.client.get(reverse("add_purchase_payment", args=[invoice.pk]), follow=True)
        self.assertRedirects(response, reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertContains(response, f"Invoice {invoice.number} is already fully paid.")

    def test_base_template_includes_bfcache_and_double_submit_protection(self):
        """Frontend safeguards against double-submit and bfcache restoration."""
        order = self.create_order()
        response = self.client.get(reverse("purchase_order_detail", args=[order.pk]))
        self.assertContains(response, "data-submitting")
        self.assertContains(response, "pageshow")
        self.assertContains(response, "window.location.reload()")

    def test_action_button_visibility_by_status(self):
        """2. Correct action-button visibility for each document status."""
        # 1. Draft PO
        order = self.create_order()
        response = self.client.get(reverse("purchase_order_detail", args=[order.pk]))
        self.assertContains(response, "Place order")
        self.assertContains(response, "Edit draft")
        self.assertContains(response, "Cancel order")
        self.assertNotContains(response, "Receive goods")

        # 2. Ordered PO
        order = services.transition_order(company=self.company, user=self.user, pk=order.pk, action="place")
        response = self.client.get(reverse("purchase_order_detail", args=[order.pk]))
        self.assertNotContains(response, "Place order")
        self.assertNotContains(response, "Edit draft")
        self.assertContains(response, "Receive goods")
        self.assertContains(response, "Cancel order")

        # 3. Partially Received PO
        receipt1 = self.confirm(self.receipt(order, accepted=20))
        order.refresh_from_db()
        self.assertEqual(order.status, "PARTIALLY_RECEIVED")
        response = self.client.get(reverse("purchase_order_detail", args=[order.pk]))
        self.assertContains(response, "Receive goods")
        self.assertNotContains(response, "Place order")
        self.assertNotContains(response, "Edit draft")
        self.assertNotContains(response, "Cancel order")

        # 4. Received PO
        receipt2 = self.confirm(self.receipt(order, accepted=30))
        order.refresh_from_db()
        self.assertEqual(order.status, "RECEIVED")
        response = self.client.get(reverse("purchase_order_detail", args=[order.pk]))
        self.assertNotContains(response, "Receive goods")
        self.assertNotContains(response, "Place order")
        self.assertNotContains(response, "Edit draft")
        self.assertNotContains(response, "Cancel order")

        # 5. Draft GRN
        new_order = self.placed_order()
        draft_grn = self.receipt(new_order)
        response = self.client.get(reverse("goods_receipt_detail", args=[draft_grn.pk]))
        self.assertContains(response, "Confirm receipt and update stock")
        self.assertContains(response, "Edit draft receipt")

        # 6. Confirmed GRN
        confirmed_grn = self.confirm(draft_grn)
        response = self.client.get(reverse("goods_receipt_detail", args=[confirmed_grn.pk]))
        self.assertNotContains(response, "Confirm receipt and update stock")
        self.assertNotContains(response, "Edit draft receipt")
        self.assertContains(response, "Received quantities are locked.")

        # 7. Pending Purchase Invoice
        invoice = confirmed_grn.invoice
        response = self.client.get(reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertContains(response, "Verify supplier bill")
        self.assertNotContains(response, "Record payment")

        # 8. Verified Purchase Invoice (outstanding > 0)
        invoice = services.reconcile_invoice(
            company=self.company, user=self.user, pk=invoice.pk,
            data={"supplier_invoice_number": "BILL-200", "invoice_date": timezone.localdate(), "tax_amount": Decimal("0"), "additional_charges": Decimal("0"), "notes": "", "verified": True}
        )
        response = self.client.get(reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertNotContains(response, "Verify supplier bill")
        self.assertContains(response, "Record payment")

        # 9. Fully Paid Invoice (outstanding == 0)
        services.record_payment(company=self.company, user=self.user, invoice_pk=invoice.pk, data=self.payment_data(amount=invoice.outstanding))
        invoice.refresh_from_db()
        response = self.client.get(reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertNotContains(response, "Verify supplier bill")
        self.assertNotContains(response, "Record payment")
        self.assertContains(response, "Paid")

    def test_repeated_place_order_attempts(self):
        """3. Repeated Place Order attempts rejected safely without duplicate effects."""
        order = self.create_order()
        # First place order
        response = self.client.post(reverse("place_purchase_order", args=[order.pk]), follow=True)
        self.assertRedirects(response, reverse("purchase_order_detail", args=[order.pk]))
        self.assertContains(response, "Purchase order updated.")
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.Status.ORDERED)

        # Repeated place order submission (e.g. Back button or repeated POST)
        response2 = self.client.post(reverse("place_purchase_order", args=[order.pk]), follow=True)
        self.assertRedirects(response2, reverse("purchase_order_detail", args=[order.pk]))
        self.assertContains(response2, "This purchase order is already placed.")
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.Status.ORDERED)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(PurchaseOrder.objects.filter(company=self.company).count(), 1)

    def test_repeated_grn_confirmation_attempts(self):
        """4. Repeated GRN confirmation attempts do not duplicate stock or invoices."""
        order = self.placed_order()
        receipt = self.receipt(order)

        # First confirmation
        response = self.client.post(reverse("confirm_goods_receipt", args=[receipt.pk]), follow=True)
        self.assertRedirects(response, reverse("goods_receipt_detail", args=[receipt.pk]))
        self.assertEqual(Inventory.objects.get(company=self.company).quantity, 30)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(PurchaseInvoice.objects.count(), 1)

        # Second confirmation (e.g. Back button or repeated POST)
        response2 = self.client.post(reverse("confirm_goods_receipt", args=[receipt.pk]), follow=True)
        self.assertRedirects(response2, reverse("goods_receipt_detail", args=[receipt.pk]))
        self.assertContains(response2, "This goods receipt is already confirmed.")

        # Inventory, movements, and invoices must remain strictly 1
        self.assertEqual(Inventory.objects.get(company=self.company).quantity, 30)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(PurchaseInvoice.objects.count(), 1)

    def test_repeated_invoice_verification_attempts(self):
        """5. Repeated invoice verification attempts rejected and locked."""
        order = self.placed_order()
        receipt = self.confirm(self.receipt(order))
        invoice = receipt.invoice

        reconcile_data = {"supplier_invoice_number": "BILL-555", "invoice_date": str(timezone.localdate()), "tax_amount": "0", "additional_charges": "0", "notes": "Verified", "verified": "on"}

        # First verification
        response = self.client.post(reverse("reconcile_purchase_invoice", args=[invoice.pk]), reconcile_data, follow=True)
        self.assertRedirects(response, reverse("purchase_invoice_detail", args=[invoice.pk]))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, PurchaseInvoice.Status.VERIFIED)
        self.assertEqual(invoice.supplier_invoice_number, "BILL-555")

        # Second verification attempt (e.g. Back button form submit)
        reconcile_data["supplier_invoice_number"] = "BILL-CHANGED"
        response2 = self.client.post(reverse("reconcile_purchase_invoice", args=[invoice.pk]), reconcile_data, follow=True)
        self.assertRedirects(response2, reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertContains(response2, "This invoice is already verified and cannot be changed.")

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, PurchaseInvoice.Status.VERIFIED)
        self.assertEqual(invoice.supplier_invoice_number, "BILL-555")
        # Ensure inventory was never affected by invoice verification
        self.assertEqual(Inventory.objects.get(company=self.company).quantity, 30)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_duplicate_and_repeated_payment_submissions(self):
        """6. Duplicate payment submission via browser history/retry."""
        invoice = self.verified_invoice()
        data = self.payment_data(amount=invoice.outstanding)

        # First payment (full payment)
        response = self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), data, follow=True)
        self.assertRedirects(response, reverse("purchase_order_list"))
        self.assertContains(response, f"Payment completed successfully for {invoice.order.number}. The purchase is fully paid.")
        self.assertEqual(PurchasePayment.objects.count(), 1)

        # Repeated payment submission with the same request_key (idempotent retry)
        response2 = self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), data, follow=True)
        self.assertRedirects(response2, reverse("purchase_order_list"))
        self.assertContains(response2, f"Payment completed successfully for {invoice.order.number}. The purchase is fully paid.")
        self.assertEqual(PurchasePayment.objects.count(), 1)

        # New payment submission with a new request_key on a fully paid invoice
        new_data = self.payment_data(amount=Decimal("50.00"), request_key=uuid.uuid4())
        response3 = self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), new_data, follow=True)
        self.assertRedirects(response3, reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertContains(response3, f"Invoice {invoice.number} is already fully paid.")
        self.assertEqual(PurchasePayment.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_overpayment_prevention(self):
        """7. Overpayment prevention."""
        invoice = self.verified_invoice()
        # Attempt to pay more than outstanding balance
        data = self.payment_data(amount=invoice.outstanding + Decimal("10.00"))
        response = self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("amount", response.context["form"].errors)
        self.assertEqual(PurchasePayment.objects.count(), 0)

    def test_correct_inventory_quantities_after_repeated_requests(self):
        """8. Correct Inventory quantities after repeated requests."""
        order = self.create_order()
        # Repeated place order
        self.client.post(reverse("place_purchase_order", args=[order.pk]))
        self.client.post(reverse("place_purchase_order", args=[order.pk]))
        self.assertFalse(Inventory.objects.filter(company=self.company).exists())

        # GRN created and confirmed repeatedly
        receipt = self.receipt(order, accepted=30)
        self.client.post(reverse("confirm_goods_receipt", args=[receipt.pk]))
        self.client.post(reverse("confirm_goods_receipt", args=[receipt.pk]))
        self.assertEqual(Inventory.objects.get(company=self.company).quantity, 30)
        self.assertEqual(StockMovement.objects.count(), 1)

        # Invoice verified repeatedly
        receipt.refresh_from_db()
        invoice = receipt.invoice
        reconcile_data = {"supplier_invoice_number": "B1", "invoice_date": str(timezone.localdate()), "tax_amount": "0", "additional_charges": "0", "verified": "on"}
        self.client.post(reverse("reconcile_purchase_invoice", args=[invoice.pk]), reconcile_data)
        self.client.post(reverse("reconcile_purchase_invoice", args=[invoice.pk]), reconcile_data)
        self.assertEqual(Inventory.objects.get(company=self.company).quantity, 30)
        self.assertEqual(StockMovement.objects.count(), 1)

        # Payment made repeatedly
        pay_data = self.payment_data(amount=invoice.outstanding)
        self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), pay_data)
        self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), pay_data)
        self.assertEqual(Inventory.objects.get(company=self.company).quantity, 30)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_full_payment_redirect_to_purchase_orders(self):
        """9. Full-payment redirect to Purchase Orders."""
        invoice = self.verified_invoice()
        response = self.client.post(
            reverse("add_purchase_payment", args=[invoice.pk]),
            self.payment_data(amount=invoice.outstanding), follow=True
        )
        self.assertRedirects(response, reverse("purchase_order_list"))
        self.assertContains(response, f"Payment completed successfully for {invoice.order.number}. The purchase is fully paid.")

    def test_partial_payment_redirect_to_invoice_detail(self):
        """10. Partial-payment redirect to invoice detail."""
        invoice = self.verified_invoice()
        response = self.client.post(
            reverse("add_purchase_payment", args=[invoice.pk]),
            self.payment_data(amount=Decimal("100.00")), follow=True
        )
        self.assertRedirects(response, reverse("purchase_invoice_detail", args=[invoice.pk]))
        self.assertContains(response, "Payment recorded. A balance of INR 200.00 remains.")
        invoice.refresh_from_db()
        self.assertEqual(invoice.outstanding, Decimal("200.00"))

    def test_tenant_isolation_on_repeated_and_direct_actions(self):
        """11. Company-owner permissions and tenant isolation."""
        invoice = self.verified_invoice()
        self.client.force_login(self.other_user)

        # Cannot access another tenant's payment form or post payment
        self.assertEqual(self.client.get(reverse("add_purchase_payment", args=[invoice.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), self.payment_data()).status_code, 404)

        # Cannot place another tenant's order
        draft = self.create_order()
        self.assertEqual(self.client.post(reverse("place_purchase_order", args=[draft.pk])).status_code, 404)

        # Cannot confirm another tenant's receipt
        receipt = self.receipt(self.placed_order())
        self.assertEqual(self.client.post(reverse("confirm_goods_receipt", args=[receipt.pk])).status_code, 404)



@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class FloatingPopupTests(PurchaseFixtures, TestCase):
    def setUp(self):
        self.make_data()
        self.client.force_login(self.user)

    def payment_data(self, **kwargs):
        return {"payment_date": timezone.localdate(), "amount": Decimal("100"), "method": "BANK", "reference": "", "notes": "", "request_key": uuid.uuid4(), **kwargs}

    def test_purchase_popup_rendering(self):
        """Purchase forms and details render in popup mode with minimal layout and action controls."""
        draft = self.create_order()
        order = self.create_order()
        services.transition_order(company=self.company, user=self.user, pk=order.pk, action="place")
        receipt = services.save_receipt(
            company=self.company, user=self.user, order_pk=order.pk,
            data={"receipt_date": timezone.localdate(), "delivery_reference": "DEL-1", "notes": ""},
            lines=[{"order_item": order.items.get(), "accepted_quantity": 20, "damaged_quantity": 0, "rejected_quantity": 0, "notes": ""}]
        )
        services.confirm_receipt(company=self.company, user=self.user, pk=receipt.pk)
        invoice = PurchaseInvoice.objects.get(receipt=receipt)

        # Pending invoice checks
        for url in [
            reverse("add_purchase_order") + "?popup=1",
            reverse("edit_purchase_order", args=[draft.pk]) + "?popup=1",
            reverse("purchase_order_detail", args=[order.pk]) + "?popup=1",
            reverse("add_goods_receipt", args=[order.pk]) + "?popup=1",
            reverse("goods_receipt_detail", args=[receipt.pk]) + "?popup=1",
            reverse("purchase_invoice_detail", args=[invoice.pk]) + "?popup=1",
            reverse("reconcile_purchase_invoice", args=[invoice.pk]) + "?popup=1",
        ]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"Failed GET {url}")
            self.assertTemplateUsed(resp, "layouts/popup_base.html")
            self.assertNotContains(resp, 'id="sidebar"')
            self.assertNotContains(resp, 'class="topbar"')

        # Verify invoice to test payment popup
        services.reconcile_invoice(
            company=self.company, user=self.user, pk=invoice.pk,
            data={"supplier_invoice_number": "BILL-POP", "invoice_date": timezone.localdate(), "tax_amount": Decimal("0"), "additional_charges": Decimal("0"), "notes": "", "verified": True}
        )
        pay_resp = self.client.get(reverse("add_purchase_payment", args=[invoice.pk]) + "?popup=1")
        self.assertEqual(pay_resp.status_code, 200)
        self.assertTemplateUsed(pay_resp, "layouts/popup_base.html")
        self.assertNotContains(pay_resp, 'id="sidebar"')

        # Verify dynamic PO line controls and live calculation targets
        po_form_resp = self.client.get(reverse("add_purchase_order") + "?popup=1")
        self.assertContains(po_form_resp, 'id="purchase-lines"')
        self.assertContains(po_form_resp, 'id="add-line"')
        self.assertContains(po_form_resp, 'id="rf-order-grand-total"')
        self.assertContains(po_form_resp, 'Save Draft')
        self.assertContains(po_form_resp, 'Save and Place Order')

    def test_purchase_order_popup_ajax_create_and_place(self):
        """Create draft and create-and-place purchase orders via popup AJAX."""
        # Save Draft via AJAX
        post_data = self.post_data()
        post_data["action"] = "save"
        resp = self.client.post(reverse("add_purchase_order"), post_data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        json_data = resp.json()
        self.assertTrue(json_data.get("success"))
        self.assertEqual(json_data.get("status"), PurchaseOrder.Status.DRAFT)
        draft = PurchaseOrder.objects.get(pk=json_data.get("pk"))
        self.assertEqual(draft.status, PurchaseOrder.Status.DRAFT)

        # Save and Place via AJAX
        post_data2 = self.post_data()
        post_data2["action"] = "save_and_place"
        resp2 = self.client.post(reverse("add_purchase_order"), post_data2, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp2.status_code, 200)
        json_data2 = resp2.json()
        self.assertTrue(json_data2.get("success"))
        self.assertEqual(json_data2.get("status"), PurchaseOrder.Status.ORDERED)
        placed = PurchaseOrder.objects.get(pk=json_data2.get("pk"))
        self.assertEqual(placed.status, PurchaseOrder.Status.ORDERED)

    def test_goods_receipt_popup_ajax_save_and_confirm(self):
        """Create and confirm Goods Receipt via popup AJAX, automatically creating invoice and updating stock."""
        order = self.create_order()
        services.transition_order(company=self.company, user=self.user, pk=order.pk, action="place")

        line = order.items.get()
        grn_data = {
            "receipt_date": str(timezone.localdate()),
            "delivery_reference": "POPUP-DEL",
            "notes": "Delivered via popup",
            "items-TOTAL_FORMS": 1,
            "items-INITIAL_FORMS": 1,
            "items-0-order_item": line.pk,
            "items-0-accepted_quantity": 50,
            "items-0-damaged_quantity": 0,
            "items-0-rejected_quantity": 0,
            "items-0-notes": "",
            "action": "confirm"
        }
        resp = self.client.post(reverse("add_goods_receipt", args=[order.pk]), grn_data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        json_data = resp.json()
        self.assertTrue(json_data.get("success"))
        self.assertTrue(json_data.get("confirmed"))

        # Verify inventory was updated
        inv = Inventory.objects.get(company=self.company, product=self.product)
        self.assertEqual(inv.quantity, 50)

        # Verify internal invoice was generated
        invoice = PurchaseInvoice.objects.get(company=self.company, order=order)
        self.assertEqual(invoice.status, PurchaseInvoice.Status.PENDING)
        self.assertEqual(invoice.grand_total, Decimal("500.00"))

    def test_invoice_reconcile_and_payments_popup_ajax(self):
        """Verify invoice, record partial payment, and record full payment via popup AJAX."""
        order = self.create_order()
        services.transition_order(company=self.company, user=self.user, pk=order.pk, action="place")
        receipt = services.save_receipt(
            company=self.company, user=self.user, order_pk=order.pk,
            data={"receipt_date": timezone.localdate(), "delivery_reference": "DEL-1", "notes": ""},
            lines=[{"order_item": order.items.get(), "accepted_quantity": 50, "damaged_quantity": 0, "rejected_quantity": 0, "notes": ""}]
        )
        services.confirm_receipt(company=self.company, user=self.user, pk=receipt.pk)
        invoice = PurchaseInvoice.objects.get(receipt=receipt)

        # 1. Verify invoice via AJAX popup
        verify_data = {
            "supplier_invoice_number": "SUP-INV-999",
            "invoice_date": str(timezone.localdate()),
            "tax_amount": "0.00",
            "additional_charges": "0.00",
            "notes": "Verified in popup",
            "verified": "on"
        }
        resp = self.client.post(reverse("reconcile_purchase_invoice", args=[invoice.pk]), verify_data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, PurchaseInvoice.Status.VERIFIED)
        self.assertEqual(invoice.outstanding, Decimal("500.00"))

        # 2. Record Partial Payment via AJAX popup
        partial_data = self.payment_data(amount=Decimal("200.00"), notes="Partial payment")
        resp_part = self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), partial_data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp_part.status_code, 200)
        part_json = resp_part.json()
        self.assertTrue(part_json.get("success"))
        self.assertEqual(part_json.get("outstanding"), 300.0)
        self.assertEqual(part_json.get("redirect_url"), reverse("purchase_invoice_detail", args=[invoice.pk]))
        invoice.refresh_from_db()
        self.assertEqual(invoice.outstanding, Decimal("300.00"))

        # 3. Record Final Payment via AJAX popup (making balance 0)
        full_data = self.payment_data(amount=Decimal("300.00"), notes="Final payment")
        resp_full = self.client.post(reverse("add_purchase_payment", args=[invoice.pk]), full_data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp_full.status_code, 200)
        full_json = resp_full.json()
        self.assertTrue(full_json.get("success"))
        self.assertEqual(full_json.get("outstanding"), 0)
        self.assertEqual(full_json.get("redirect_url"), reverse("purchase_order_list"))
        self.assertEqual(full_json.get("message"), f"Payment completed successfully for {order.number}. The purchase is fully paid.")
        invoice.refresh_from_db()
        self.assertEqual(invoice.outstanding, Decimal("0.00"))
