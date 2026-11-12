from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from accounts.forms import Loginform
from accounts.models import User
from company.context import get_current_tenant
from employees.forms import EmployeeForm, EmployeeEditForm
from employees.models import Employee
from .permissions import role_required


@login_required
def create_employee(request):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"

    company = getattr(request.user, "company", None) or get_current_tenant()
    if not company:
        if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "No company associated with your account."}, status=400)
        messages.error(request, "No company associated with your account.")
        return redirect("employee_list")

    if request.method == "POST":
        form = EmployeeForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]

            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                is_verified=True,
            )

            employee = form.save(commit=False)
            employee.user = user
            employee.company = company
            employee.save()

            messages.success(request, f"Employee {employee.first_name} {employee.last_name} created successfully.")
            if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({
                    "success": True,
                    "message": f"Employee {employee.first_name} {employee.last_name} created successfully.",
                    "id": employee.pk,
                    "name": f"{employee.first_name} {employee.last_name}",
                    "redirect_url": reverse("employee_list")
                })
            return redirect("employee_list")
        else:
            if is_popup and request.headers.get("x-requested-with") == "XMLHttpRequest":
                return render(request, "employees/create_employee.html", {
                    "form": form,
                    "is_popup": True,
                    "base_template": base_template
                }, status=400)
    else:
        form = EmployeeForm()

    return render(request, "employees/create_employee.html", {
        "form": form,
        "is_popup": is_popup,
        "base_template": base_template
    })


@login_required
def edit_employee(request, pk):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"
    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"

    company = getattr(request.user, "company", None) or get_current_tenant()
    employee = get_object_or_404(Employee, pk=pk, company=company)

    if request.method == "POST":
        form = EmployeeEditForm(request.POST, instance=employee)
        if form.is_valid():
            employee = form.save()
            messages.success(request, f"Employee {employee.first_name} {employee.last_name} updated successfully.")
            if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({
                    "success": True,
                    "message": f"Employee {employee.first_name} {employee.last_name} updated successfully.",
                    "id": employee.pk,
                    "name": f"{employee.first_name} {employee.last_name}",
                    "redirect_url": reverse("employee_list")
                })
            return redirect("employee_list")
        else:
            if is_popup and request.headers.get("x-requested-with") == "XMLHttpRequest":
                return render(request, "employees/edit_employee.html", {
                    "form": form,
                    "employee": employee,
                    "is_popup": True,
                    "base_template": base_template
                }, status=400)
    else:
        form = EmployeeEditForm(instance=employee)

    return render(request, "employees/edit_employee.html", {
        "form": form,
        "employee": employee,
        "is_popup": is_popup,
        "base_template": base_template
    })


@login_required
def employee_list(request):
    company = getattr(request.user, "company", None) or get_current_tenant()
    employees = Employee.objects.filter(company=company) if company else Employee.objects.none()

    return render(
        request,
        "employees/employee_list.html",
        {
            "employees": employees
        }
    )


def employee_login(request):
    if request.method=="POST":
        form = Loginform(request.POST)

        if form.is_valid():
            user = form.cleaned_data["user"]

            if not hasattr(user,"employee"):
                form.add_error(
                    None,
                    "This account is not an employee account."
                )

            else:
                login(request, user)
                employee = user.employee
                employee.is_online =True
                employee.save()

                if employee.role == "MANAGER":
                    return redirect("manager_dashboard")
                elif employee.role == "CASHIER":
                    return redirect("pos_sales_history")
                elif employee.role == "INVENTORY":
                    return redirect("inventory")
                else:

                    return redirect("employee_dashboard")
    else:
        form = Loginform()

    return render(request, "employees/login.html", {"form": form})

@role_required("MANAGER")
def manager_dashboard(request):

    if not hasattr(request.user, "employee"):
        return redirect("employee_login")

    employee = request.user.employee

    # Only Manager can access this dashboard
    if employee.role != "MANAGER":
        return redirect("employee_dashboard")



    context = {
        "employee": employee,

        # Temporary dashboard data
        # We will connect these to the database later.
        "total_sales": "48,620",
        "total_orders": 86,
        "total_customers": 52,
        "low_stock_items": 5,

        "sales_change": 12,
        "orders_change": 8,
        "customers_change": 16,

        "top_products": [
            {
                "name": "Rice (5kg)",
                "sold": 24,
                "amount": "6,000",
            },
            {
                "name": "Cooking Oil (1L)",
                "sold": 18,
                "amount": "4,500",
            },
            {
                "name": "Sugar (1kg)",
                "sold": 16,
                "amount": "1,600",
            },
            {
                "name": "Tea (250g)",
                "sold": 12,
                "amount": "1,200",
            },
            {
                "name": "Biscuits",
                "sold": 10,
                "amount": "1,000",
            },
        ],

        "recent_sales": [
            {
                "invoice": "SR-1042",
                "customer": "Rahul Nair",
                "items": 5,
                "amount": "1,250",
                "time": "10:18 AM",
            },
            {
                "invoice": "SR-1041",
                "customer": "Sanoop K",
                "items": 3,
                "amount": "780",
                "time": "10:05 AM",
            },
            {
                "invoice": "SR-1040",
                "customer": "Ayesha M",
                "items": 7,
                "amount": "2,340",
                "time": "09:52 AM",
            },
            {
                "invoice": "SR-1039",
                "customer": "Fahad P",
                "items": 2,
                "amount": "560",
                "time": "09:36 AM",
            },
            {
                "invoice": "SR-1038",
                "customer": "Deepa S",
                "items": 4,
                "amount": "1,120",
                "time": "09:20 AM",
            },
        ],

        "activities": [
            {
                "title": "New sale completed",
                "description": "Invoice SR-1042 • ₹1,250",
                "time": "10:18 AM",
                "icon": "🛒",
            },
            {
                "title": "Product added to inventory",
                "description": "Rice (5kg) • 50 units",
                "time": "09:45 AM",
                "icon": "📦",
            },
            {
                "title": "Purchase order created",
                "description": "Supplier: Kerala Foods • ₹12,000",
                "time": "09:20 AM",
                "icon": "📄",
            },
            {
                "title": "Low stock alert",
                "description": "Cooking Oil (1L) • 3 remaining",
                "time": "08:50 AM",
                "icon": "⚠️",
            },
            {
                "title": "Employee login",
                "description": "Rahul (Cashier)",
                "time": "08:32 AM",
                "icon": "👤",
            },
        ],
    }

    return render(
        request,
        "employees/manager_dashboard.html",
        context
    )


@role_required("INVENTORY")
def inventory(request):

    if not hasattr(request.user, "employee"):
        return redirect("employee_login")

    employee = request.user.employee

    if employee.role != "INVENTORY":
        return redirect("employee_dashboard")

    return render(
        request,
        "employees/inventory.html",
        {
            "employee": employee
        }
    )

@login_required
def employee_dashboard(request):
    if not hasattr(request.user,"employee"):
        return redirect("employee_login")

    employee = request.user.employee

    return render(request,"employees/dashboard.html",{"employee":employee})

def employee_logout(request):
    if request.user.is_authenticated:
        if hasattr(request.user, "employee"):
            employee =request.user.employee
            employee.is_online=False
            employee.save()

        logout(request)

    return redirect("employee_login")




