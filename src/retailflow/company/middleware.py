from django.core.exceptions import ObjectDoesNotExist

from company.context import (
    set_current_tenant,
    set_current_branch,
    reset_current_tenant,
    reset_current_branch,
)


class TenantMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # Step 1: Identify the logged-in user's company
        company = self.get_user_company(request.user)

        # Step 2: Store the tenant and branch context
        tenant_token = set_current_tenant(company)
        branch_token = set_current_branch(None)

        try:
            # Step 3: Continue processing the request
            response = self.get_response(request)
            return response

        finally:
            # Step 4: Clear temporary request context
            reset_current_branch(branch_token)
            reset_current_tenant(tenant_token)

    @staticmethod
    def get_user_company(user):

        # Anonymous users have no company
        if not user.is_authenticated:
            return None

        # Check whether this user is an employee
        try:
            employee = user.employee
            return employee.company

        except (AttributeError, ObjectDoesNotExist):
            pass

        # Otherwise, check whether this user owns a company
        try:
            return user.company

        except (AttributeError, ObjectDoesNotExist):
            return None