"""User model for DevForge.

Email is the identity — there is no username. A custom user model is introduced
here, before any other app references it, because swapping AUTH_USER_MODEL later
is extremely costly. Organization membership lives in apps.organizations.
"""
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(models.Manager):
    """Manager that creates users keyed by email."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    @staticmethod
    def normalize_email(email):
        # Lowercase the domain part; leave the local part as-is (RFC-safe).
        email = email or ""
        try:
            local, domain = email.strip().rsplit("@", 1)
        except ValueError:
            return email.strip()
        return f"{local}@{domain.lower()}"

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        # Required by Django auth (login, createsuperuser). Look up by email,
        # the USERNAME_FIELD.
        return self.get(**{self.model.USERNAME_FIELD: username})


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False,
        help_text="Whether the user can log into the Django admin site.",
    )
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # email + password are already required by USERNAME_FIELD

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email

    @property
    def short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.email
