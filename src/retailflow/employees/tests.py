from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from company.models import Company
from employees.models import Employee

User = get_user_model()


class EmployeePopupTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            email="owner@test.com",
            password="Password@123",
            first_name="Owner",
            last_name="User",
            is_verified=True,
        )
        self.company = Company.objects.create(
            user=self.owner,
            company_name="Test Company",
            company_registration_number="TC01",
            state="Kerala",
            country="India",
            phone="1234567890",
            email="owner@test.com",
            address="123 Main St",
        )
        self.owner.company = self.company
        self.owner.save()
        self.client.force_login(self.owner)

    def test_create_employee_popup_render(self):
        url = reverse("create_employee") + "?popup=1"
        response = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_X_RF_WINDOW="1")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context.get("is_popup"))
        self.assertContains(response, "Add Employee")
        self.assertContains(response, "name=\"first_name\"")

    def test_create_employee_ajax_post_success(self):
        url = reverse("create_employee")
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "role": "CASHIER",
            "email": "johndoe@test.com",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!",
            "popup": "1",
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_X_RF_WINDOW="1")
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertTrue(json_data.get("success"))
        self.assertTrue(Employee.objects.filter(user__email="johndoe@test.com", company=self.company).exists())

    def test_create_employee_ajax_post_password_mismatch(self):
        url = reverse("create_employee")
        data = {
            "first_name": "Jane",
            "last_name": "Doe",
            "role": "CASHIER",
            "email": "janedoe@test.com",
            "password": "PasswordA123!",
            "confirm_password": "PasswordB123!",
            "popup": "1",
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_X_RF_WINDOW="1")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Passwords do not match", status_code=400)

    def test_edit_employee_popup_render(self):
        emp_user = User.objects.create_user(
            email="emp@test.com",
            password="Password@123",
            first_name="Emp",
            last_name="Loyee",
            is_verified=True,
        )
        employee = Employee.objects.create(
            user=emp_user,
            company=self.company,
            first_name="Emp",
            last_name="Loyee",
            role="CASHIER",
        )
        url = reverse("edit_employee", args=[employee.pk]) + "?popup=1"
        response = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_X_RF_WINDOW="1")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context.get("is_popup"))
        self.assertContains(response, "Edit Employee")
        self.assertContains(response, "value=\"Emp\"")

    def test_edit_employee_ajax_post_success(self):
        emp_user = User.objects.create_user(
            email="staff@test.com",
            password="Password@123",
            first_name="Staff",
            last_name="Member",
            is_verified=True,
        )
        employee = Employee.objects.create(
            user=emp_user,
            company=self.company,
            first_name="Staff",
            last_name="Member",
            role="CASHIER",
        )
        url = reverse("edit_employee", args=[employee.pk])
        data = {
            "first_name": "UpdatedStaff",
            "last_name": "UpdatedMember",
            "role": "MANAGER",
            "email": "updatedstaff@test.com",
            "popup": "1",
        }
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_X_RF_WINDOW="1")
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertTrue(json_data.get("success"))
        employee.refresh_from_db()
        self.assertEqual(employee.first_name, "UpdatedStaff")
        self.assertEqual(employee.role, "MANAGER")
        self.assertEqual(employee.user.email, "updatedstaff@test.com")
