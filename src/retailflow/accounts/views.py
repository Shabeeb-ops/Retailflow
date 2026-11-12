
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from datetime import timedelta
from decimal import Decimal
from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from employees.models import Employee
from products.models import Product
from inventory.models import Inventory, StockMovement
from .models import User
from .forms import SignupForm, Loginform


def signup_view(request):

    if request.method == "POST":

        form = SignupForm(request.POST)

        if form.is_valid():

            user = form.save(commit=False)

            user.set_password(
                form.cleaned_data["password"]
            )

            user.is_verified = False

            user.save()

            return render(
                request,
                "accounts/verification_sent.html"
            )

    else:

        form = SignupForm()

    return render(
        request,
        "accounts/signup.html",
        {"form": form}
    )
def login_view(request):

    if request.method == "POST":

        form = Loginform(request.POST)

        if form.is_valid():

            user = form.cleaned_data["user"]

            login(request, user)

            if hasattr(user, "employee"):
                user.employee.is_online = True
                user.employee.save()
                if user.employee.role == "CASHIER":
                    return redirect("pos_sales_history")
                elif user.employee.role == "MANAGER":
                    return redirect("manager_dashboard")
                elif user.employee.role == "INVENTORY":
                    return redirect("inventory")
                else:
                    return redirect("employee_dashboard")

            return redirect("company_registration")

    else:

        form = Loginform()

    return render(
        request,
        "accounts/login.html",
        {"form": form}
    )

def verify_email_view(request, uid, token):

    try:

        # 1. Convert UID back to the original user ID
        user_id = force_str(
            urlsafe_base64_decode(uid)
        )

        # 2. Find that user in the database
        user = User.objects.get(
            id=user_id
        )

    except User.DoesNotExist:

        return render(
            request,
            "accounts/verification_failed.html"
        )

    # 3. Check whether the token is valid
    if default_token_generator.check_token(
        user,
        token
    ):

        # 4. Mark the user's email as verified
        user.is_verified = True

        user.save()

        # 5. Send the user to login page
        return redirect("login")

    # 6. Token is invalid or expired
    return render(
        request,
        "accounts/verification_failed.html"
    )


@login_required
def dashboard_view(request):

    if not hasattr(request.user,"company"):
        return redirect("company_registration")
    company = request.user.company
    products = Product.objects.filter(company=company, is_active=True).annotate(
        stock=Coalesce(Sum("inventory_records__quantity", filter=Q(
            inventory_records__company=company)), 0)
    )
    inventory = Inventory.objects.filter(
        company=company, product__company=company, product__is_active=True
    )
    totals = inventory.aggregate(
        units=Sum("quantity"), damaged=Sum("damaged_quantity"),
        value=Sum(F("quantity") * F("product__purchase_price"),
                  output_field=DecimalField(max_digits=20, decimal_places=2)),
    )
    low_stock = products.filter(stock__gt=0, stock__lte=F("low_stock_threshold"))
    out_of_stock = products.filter(stock=0)
    employees = Employee.objects.filter(company=company).aggregate(
        total=Count("pk"), online=Count("pk", filter=Q(is_online=True))
    )
    movements = StockMovement.objects.filter(
        inventory__company=company, inventory__product__company=company
    )
    today = timezone.localdate()
    start = today - timedelta(days=6)
    daily = dict(movements.filter(created_at__date__range=(start, today))
                 .annotate(day=TruncDate("created_at")).values("day")
                 .annotate(units=Sum("quantity")).values_list("day", "units"))
    days = [start + timedelta(days=i) for i in range(7)]
    values = [daily.get(day, 0) for day in days]
    chart_max = max(max(values), 1)
    context = {
        "company": company, "today": today, "chart_start": start,
        "total_products": products.count(), "stock_units": totals["units"] or 0,
        "damaged_units": totals["damaged"] or 0,
        "stock_value": totals["value"] or Decimal("0.00"),
        "low_stock_count": low_stock.count(), "out_of_stock_count": out_of_stock.count(),
        "stock_alerts": products.filter(stock__lte=F("low_stock_threshold"))
                                .order_by("stock", "name")[:3],
        "employee_count": employees["total"], "online_count": employees["online"],
        "branch_count": company.branches.filter(is_active=True).count(),
        "recent_movements": movements.select_related("inventory__product")[:3],
        "chart_total": sum(values), "chart_has_data": bool(daily),
        "chart_max": chart_max, "chart_mid": chart_max / 2,
        "chart_points": " ".join(f"{14+i*92},{100-value/chart_max*100:.2f}"
                                  for i, value in enumerate(values)),
        "chart_days": [{"label": day.strftime("%a"), "date": day, "value": value}
                       for day, value in zip(days, values)],
    }
    return render(request, "dashboard/home.html", context)


def logout_view(request):
    if hasattr(request.user, "employee"):
        request.user.employee.is_online = False
        request.user.employee.save()


    logout(request)

    return redirect("login")


