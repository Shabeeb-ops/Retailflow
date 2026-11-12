from django import forms
from .models import Employee
from accounts.models import User


class EmployeeForm(forms.ModelForm):

    email = forms.EmailField()

    password = forms.CharField(
        widget=forms.PasswordInput
    )

    confirm_password = forms.CharField(
        widget=forms.PasswordInput
    )

    class Meta:
        model = Employee

        fields = [
            "first_name",
            "last_name",
            "role",
        ]

    def clean_email(self):
        email = self.cleaned_data["email"]

        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )

        return email

    def clean(self):
        cleaned_data = super().clean()

        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password:
            if password != confirm_password:
                raise forms.ValidationError(
                    "Passwords do not match."
                )

        return cleaned_data


class EmployeeEditForm(forms.ModelForm):
    email = forms.EmailField()

    class Meta:
        model = Employee
        fields = [
            "first_name",
            "last_name",
            "role",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.user:
            self.fields["email"].initial = self.instance.user.email

    def clean_email(self):
        email = self.cleaned_data["email"]
        existing = User.objects.filter(email=email)
        if self.instance and self.instance.pk and self.instance.user:
            existing = existing.exclude(pk=self.instance.user.pk)
        if existing.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        employee = super().save(commit=False)
        if employee.user:
            employee.user.email = self.cleaned_data["email"]
            employee.user.first_name = employee.first_name
            employee.user.last_name = employee.last_name
            if commit:
                employee.user.save()
        if commit:
            employee.save()
        return employee
