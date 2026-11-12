from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect


class CashierAccessMiddleware:
    """
    Enforces strict access boundary for Cashier accounts:
    - Cashiers can ONLY access:
        1. POS Terminal (/employees/cashier/ and /pos/)
        2. POS Sales History (/pos/history/ and /pos/history/<sale_id>/)
        3. POS Reports (/pos/reports/)
        4. POS Operations (/pos/checkout/, /pos/receipt/*, /pos/hold/, /pos/recall/*, /pos/held-carts/*, /pos/barcode/*)
        5. Employee logout (/employees/logout/, /accounts/logout/)
        6. Static/Media assets

    - Any attempt to access restricted administrative areas (e.g., Dashboard,
      Products, Inventory, Suppliers, Purchases, Employees, Branches, POS Settings)
      is automatically intercepted and redirected to the POS Terminal.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and hasattr(request.user, "employee"):
            employee = request.user.employee
            if employee and employee.role == "CASHIER":
                path = request.path

                is_pos_terminal = path in ("/employees/cashier/", "/pos", "/pos/")
                is_pos_subpath = path.startswith("/pos/") and not path.startswith("/pos/settings")
                is_logout = (
                    path.startswith("/employees/logout")
                    or path.startswith("/accounts/logout")
                    or path.startswith("/logout")
                )
                is_asset = path.startswith("/static/") or path.startswith("/media/")

                if not (is_pos_terminal or is_pos_subpath or is_logout or is_asset):
                    if (
                        request.headers.get("x-requested-with") == "XMLHttpRequest"
                        or "application/json" in request.headers.get("accept", "")
                    ):
                        return JsonResponse(
                            {
                                "error": "Permission denied: Cashiers can only access the POS Terminal, Sales History, and Sales Reports."
                            },
                            status=403,
                        )

                    messages.warning(
                        request,
                        "Cashiers only have access to the POS Terminal, Sales History, and Sales Reports."
                    )
                    return redirect("pos_sales_history")

        return self.get_response(request)

