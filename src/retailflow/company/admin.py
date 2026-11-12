

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, path, reverse
from django.utils.html import format_html

from .models import Company
from employees.models import Employee
from products.models import Category, Product
from inventory.models import Inventory, StockMovement


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):

    list_display = (
        "company_name",
        "user",
        "created_at",
        "open_workspace",
    )

    search_fields = (
        "company_name",
        "email",
        "company_registration_number",
    )

    change_form_template = (
        "admin/company/company/change_form.html"
    )

    # Link to the company ERP workspace
    @admin.display(description="ERP Workspace")
    def open_workspace(self, obj):
        url = reverse(
            "admin:company_company_change",
            args=[obj.pk],
        )

        return format_html(
            '<a href="{}">Open Workspace</a>',
            url,
        )

    # Register custom ERP section URLs
    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/erp/<slug:section>/",
                self.admin_site.admin_view(
                    self.erp_section_view
                ),
                name="company_company_erp_section",
            ),
        ]

        return custom_urls + super().get_urls()

    # Get data belonging to the selected company
    def _section_querysets(self, company):

        return {
            "employees": (
                "Employees",
                Employee.objects.filter(
                    company=company
                ),
            ),

            "products": (
                "Products",
                Product.objects.filter(
                    company=company
                ).select_related("category"),
            ),

            "categories": (
                "Categories",
                Category.objects.filter(
                    company=company
                ),
            ),

            "inventory": (
                "Inventory",
                Inventory.objects.filter(
                    company=company
                ).select_related("product"),
            ),

            "stock-movements": (
                "Stock Movements",
                StockMovement.objects.filter(
                    inventory__company=company
                ).select_related(
                    "inventory__product"
                ),
            ),
        }

    # Add ERP section cards to the Company edit page
    def render_change_form(
        self,
        request,
        context,
        add=False,
        change=False,
        form_url="",
        obj=None,
    ):

        if obj is not None and request.user.is_superuser:

            sections = self._section_querysets(obj)

            context["rf_sections"] = [
                {
                    "label": label,
                    "count": queryset.count(),
                    "url": reverse(
                        "admin:company_company_erp_section",
                        args=[obj.pk, slug],
                    ),
                }

                for slug, (label, queryset) in sections.items()
            ]

        return super().render_change_form(
            request,
            context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )

    # Display record details in each ERP section
    @staticmethod
    def _describe(section, item):

        if section == "employees":
            return (
                f"{item.first_name} {item.last_name}".strip(),
                f"{item.employee_id} - "
                f"{item.get_role_display()}",
            )

        if section == "products":
            return (
                item.name,
                f"SKU: {item.sku} - "
                f"Category: {item.category.name}",
            )

        if section == "categories":
            return (
                item.name,
                "Active" if item.is_active else "Inactive",
            )

        if section == "inventory":
            return (
                item.product.name,
                f"SKU: {item.product.sku} - "
                f"Available: {item.quantity} - "
                f"Damaged: {item.damaged_quantity}",
            )

        return (
            item.inventory.product.name,
            f"{item.get_movement_type_display()} - "
            f"Qty: {item.quantity} - "
            f"{item.created_at:%Y-%m-%d %H:%M}",
        )

    # Show all records of a selected ERP section
    def erp_section_view(
        self,
        request,
        object_id,
        section,
    ):

        # Only Django system superusers can access
        # the company ERP workspace.
        if not request.user.is_superuser:
            raise PermissionDenied(
                "System superuser access is required."
            )

        company = self.get_object(
            request,
            object_id,
        )

        if company is None:
            raise Http404("Company not found")

        sections = self._section_querysets(company)

        if section not in sections:
            raise Http404("Unknown company section")

        label, queryset = sections[section]

        # Search inside the current company's records
        search = request.GET.get(
            "q", ""
        ).strip()[:100]

        if search:

            if section == "employees":
                condition = (
                    Q(first_name__icontains=search)
                    | Q(last_name__icontains=search)
                    | Q(employee_id__icontains=search)
                )

            elif section == "products":
                condition = (
                    Q(name__icontains=search)
                    | Q(sku__icontains=search)
                    | Q(brand__icontains=search)
                )

            elif section == "categories":
                condition = Q(
                    name__icontains=search
                )

            elif section == "inventory":
                condition = (
                    Q(product__name__icontains=search)
                    | Q(product__sku__icontains=search)
                )

            else:
                condition = (
                    Q(
                        inventory__product__name__icontains=search
                    )
                    | Q(
                        inventory__product__sku__icontains=search
                    )
                    | Q(reason__icontains=search)
                )

            queryset = queryset.filter(condition)

        # Pagination: 25 records per page
        paginator = Paginator(
            queryset.order_by("-pk"),
            25,
        )

        page_obj = paginator.get_page(
            request.GET.get("page")
        )

        rows = []

        for item in page_obj:

            title, details = self._describe(
                section,
                item,
            )

            admin_url = None

            try:
                admin_url = reverse(
                    f"admin:{item._meta.app_label}_"
                    f"{item._meta.model_name}_change",
                    args=[item.pk],
                )

            except NoReverseMatch:
                pass

            rows.append({
                "title": title,
                "details": details,
                "url": admin_url,
            })

        overview_url = reverse(
            "admin:company_company_change",
            args=[company.pk],
        )

        context = {
            **self.admin_site.each_context(request),

            "title": (
                f"{company.company_name} - {label}"
            ),

            "company": company,
            "section_label": label,
            "rows": rows,
            "page_obj": page_obj,
            "search_query": search,
            "overview_url": overview_url,
            "opts": self.model._meta,
        }

        return TemplateResponse(
            request,
            "admin/company/company/erp_section.html",
            context,
        )

