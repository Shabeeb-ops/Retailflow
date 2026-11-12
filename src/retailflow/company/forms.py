from django import forms
from .models import Company
from .models import Branch

class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company

        fields = [
            "company_registration_number",
            "company_name",
            "address",
            "state",
            "country",
            "currency",
            "phone",
            "email",

        ]


class BranchForm(forms.ModelForm):

    class Meta:
        model = Branch

        fields = [
            "name",
            "code",
            "branch_type",
            "address",
            "phone",
            "email",
            "is_active",
        ]

        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "Main Store",
            }),

            "code": forms.TextInput(attrs={
                "placeholder": "BR-001",
            }),

            "address": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Enter branch address",
            }),

            "phone": forms.TextInput(attrs={
                "placeholder": "Branch phone number",
            }),

            "email": forms.EmailInput(attrs={
                "placeholder": "branch@example.com",
            }),
        }

    def clean_code(self):
        code = self.cleaned_data["code"]

        # Standardize branch codes.
        return code.strip().upper()
