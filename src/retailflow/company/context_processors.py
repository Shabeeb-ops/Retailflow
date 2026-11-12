from company.context import get_current_tenant


def tenant_context(request):
    """Provide the current tenant company to all templates."""
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {}

    company = get_current_tenant()
    if company is None and hasattr(request.user, "company"):
        try:
            company = request.user.company
        except Exception:
            company = None

    return {
        "company": company,
    }
