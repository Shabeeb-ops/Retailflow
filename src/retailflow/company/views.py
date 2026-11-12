
from django.shortcuts import render, redirect
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import CompanyForm
from .models import Company
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from company.context import get_current_tenant
from .models import Branch
from .forms import BranchForm



@login_required
def company_registration(request):

    if hasattr(request.user, "company"):
        return redirect("dashboard_view")

    if request.method == "POST":
        form = CompanyForm(request.POST)

        if form.is_valid():
            company = form.save(commit=False)
            company.user = request.user
            company.save()
            return redirect("dashboard_view")

    else:
        form = CompanyForm()

    return render(request,"company/company_registration.html",{"form":form})


@login_required
@require_GET
def branch_list(request):

    # Get the company identified by TenantMiddleware.
    company = get_current_tenant()

    if company is None:
        raise PermissionDenied(
            "No company is associated with this account."
        )

    # Only the company owner can manage branches for now.
    if company.user_id != request.user.pk:
        raise PermissionDenied(
            "Only the company owner can manage branches."
        )

    # Fetch only this company's branches.
    branches = Branch.objects.filter(
        company=company
    ).order_by("name", "pk")

    return render(
        request,
        "company/branch_list.html",
        {
            "company": company,
            "branches": branches,
        },
    )

@login_required
@require_http_methods(["GET", "POST"])
def add_branch(request):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"

    # Identify the current tenant.
    company = get_current_tenant()

    if company is None:
        raise PermissionDenied(
            "No company is associated with this account."
        )

    # Only the owner can create branches for now.
    if company.user_id != request.user.pk:
        raise PermissionDenied(
            "Only the company owner can create branches."
        )

    if request.method == "POST":

        form = BranchForm(request.POST)

        if form.is_valid():

            code = form.cleaned_data["code"]

            # Check duplicate codes within this company.
            duplicate_exists = Branch.objects.filter(
                company=company,
                code__iexact=code,
            ).exists()

            if duplicate_exists:
                form.add_error(
                    "code",
                    "This branch code already exists in your company."
                )

            else:
                try:
                    with transaction.atomic():

                        # Form does not let users choose a company.
                        branch = form.save(commit=False)

                        # Always assign the logged-in user's company.
                        branch.company = company

                        branch.save()

                except IntegrityError:
                    form.add_error(
                        "code",
                        "This branch code could not be saved. "
                        "It may already exist."
                    )

                else:
                    msg = "Branch created successfully."
                    messages.success(request, msg)

                    if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                        return JsonResponse({
                            "success": True,
                            "message": msg,
                            "pk": str(branch.pk),
                            "name": branch.name,
                            "redirect_url": reverse("branch_list")
                        })

                    return redirect("branch_list")

    else:
        form = BranchForm()

    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"
    return render(
        request,
        "company/branch_form.html",
        {
            "form": form,
            "company": company,
            "is_popup": is_popup,
            "base_template": base_template,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def edit_branch(request, branch_id):
    is_popup = request.GET.get("popup") == "1" or request.POST.get("popup") == "1" or request.headers.get("x-rf-window") == "1"

    company = get_current_tenant()

    if company is None:
        raise PermissionDenied(
            "No company is associated with this account."
        )

    # Only the company owner can edit branches.
    if company.user_id != request.user.pk:
        raise PermissionDenied(
            "Only the company owner can edit branches."
        )

    # Prevent editing another company's branch.
    branch = get_object_or_404(
        Branch,
        pk=branch_id,
        company=company,
    )

    if request.method == "POST":
        form = BranchForm(
            request.POST,
            instance=branch,
        )

        if form.is_valid():

            code = form.cleaned_data["code"]

            duplicate_exists = Branch.objects.filter(
                company=company,
                code__iexact=code,
            ).exclude(
                pk=branch.pk
            ).exists()

            if duplicate_exists:
                form.add_error(
                    "code",
                    "This branch code already exists."
                )
            else:
                try:
                    with transaction.atomic():
                        form.save()

                except IntegrityError:
                    form.add_error(
                        "code",
                        "This branch code could not be saved."
                    )

                else:
                    msg = "Branch updated successfully."
                    messages.success(request, msg)

                    if is_popup or request.headers.get("x-requested-with") == "XMLHttpRequest":
                        return JsonResponse({
                            "success": True,
                            "message": msg,
                            "pk": str(branch.pk),
                            "name": branch.name,
                            "redirect_url": reverse("branch_list")
                        })

                    return redirect("branch_list")

    else:
        form = BranchForm(instance=branch)

    base_template = "layouts/popup_base.html" if is_popup else "layouts/admin_base.html"
    return render(
        request,
        "company/branch_form.html",
        {
            "form": form,
            "company": company,
            "branch": branch,
            "editing": True,
            "is_popup": is_popup,
            "base_template": base_template,
        },
    )
