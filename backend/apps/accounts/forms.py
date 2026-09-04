"""Admin forms bound to the email-based custom user model."""
from django import forms
from django.contrib.auth.forms import (
    BaseUserCreationForm,
    UserChangeForm as BaseUserChangeForm,
)

from apps.accounts.models import User


class UserCreationForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("email", "full_name")
        field_classes = {"email": forms.EmailField}


class UserChangeForm(BaseUserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
        field_classes = {"email": forms.EmailField}
