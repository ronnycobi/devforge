from django.contrib import admin

from apps.organizations.models import (
    Invitation,
    Membership,
    Organization,
    Team,
    TeamMembership,
)


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "created_by", "created_at"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["organization", "user", "role", "created_at"]
    list_filter = ["role"]
    search_fields = ["organization__name", "user__email"]
    autocomplete_fields = ["organization", "user"]


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "slug", "created_at"]
    search_fields = ["name", "organization__name"]
    autocomplete_fields = ["organization"]
    inlines = [TeamMembershipInline]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ["email", "organization", "role", "status", "created_at", "expires_at"]
    list_filter = ["status", "role"]
    search_fields = ["email", "organization__name"]
    autocomplete_fields = ["organization", "team", "invited_by"]
    readonly_fields = ["token", "created_at", "accepted_at"]
