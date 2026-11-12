from django import forms
from django.contrib.auth import authenticate
from .models import User

class SignupForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput
    )

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'password'

        ]
    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )

        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("confirm_password"):
            raise forms.ValidationError(
                 "Passwords do not match."
            )
        return cleaned

class Loginform(forms.Form):
    email = forms.EmailField()
    password =forms.CharField(
        widget=forms.PasswordInput
    )
    def clean(self):
        cleaned_data = super().clean()

        email = cleaned_data.get('email')
        password = cleaned_data.get('password')

        if email and password:
            user = authenticate(
                email = email,
                password = password
            )
            if user is None:
                raise forms.ValidationError(
                    "invalid email or password"
                )
            if not user.is_verified:
                raise forms.ValidationError(
                    "Please verify your email before logging in."
                )
            if not user.is_active:
                raise forms.ValidationError(
                    "This account is inactive"
                )

            cleaned_data["user"] = user
        return cleaned_data
            