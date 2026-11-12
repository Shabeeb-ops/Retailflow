from functools import wraps

from django.contrib.auth.base_user import AbstractBaseUser
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request,*args, **kwargs):

            if not request.user.is_authenticated:
                return redirect("employee_login")

            if not hasattr(request.user , "employee"):
                return HttpResponseForbidden(
                    "Your are not an employee."
                )

            employee = request.user.employee

            if employee.role not in allowed_roles:
                return HttpResponseForbidden("You do not have permission to access this page.")
            return view_func(request, *args, **kwargs)

        return wrapper
    return decorator

