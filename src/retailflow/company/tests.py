from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from company.models import Company, Branch


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class BranchPopupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="branch-owner@example.com", password="password", is_verified=True)
        self.company = Company.objects.create(user=self.user, company_name="Branch Retail", currency="INR")
        self.client.force_login(self.user)
        self.branch = Branch.objects.create(
            company=self.company,
            name="Main Outlet",
            code="BR-001",
            branch_type="RETAIL_STORE",
            is_active=True
        )

    def test_branch_popup_rendering(self):
        """Branch forms render with minimal popup layout."""
        for url in [
            reverse("add_branch") + "?popup=1",
            reverse("edit_branch", args=[self.branch.pk]) + "?popup=1",
        ]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertTemplateUsed(resp, "layouts/popup_base.html")
            self.assertNotContains(resp, 'id="sidebar"')

    def test_add_branch_popup_ajax_success(self):
        """Add branch via popup AJAX saves to PostgreSQL and returns JSON."""
        data = {
            "name": "North Warehouse",
            "code": "WH-002",
            "branch_type": "WAREHOUSE",
            "address": "123 Industrial Way",
            "phone": "9876543210",
            "email": "wh2@example.com",
            "is_active": True
        }
        resp = self.client.post(
            reverse("add_branch"),
            data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.json()
        self.assertTrue(json_data.get("success"))
        created = Branch.objects.get(company=self.company, code="WH-002")
        self.assertEqual(created.name, "North Warehouse")

    def test_edit_branch_popup_ajax_success(self):
        """Edit branch via popup AJAX updates record and returns JSON."""
        data = {
            "name": "Main Flagship Store",
            "code": "BR-001",
            "branch_type": "RETAIL_STORE",
            "address": "Central Plaza",
            "is_active": True
        }
        resp = self.client.post(
            reverse("edit_branch", args=[self.branch.pk]),
            data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.name, "Main Flagship Store")

    def test_branch_popup_ajax_validation_duplicate_code(self):
        """Duplicate branch code keeps popup open showing validation error."""
        data = {
            "name": "Another Store",
            "code": "BR-001",  # duplicate code
            "branch_type": "RETAIL_STORE",
            "is_active": True
        }
        resp = self.client.post(
            reverse("add_branch") + "?popup=1",
            data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")
