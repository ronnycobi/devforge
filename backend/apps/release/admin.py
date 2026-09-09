from django.contrib import admin

from apps.release.models import (
    MobileApplication, MobileBuild, Release, ReleaseEvent, SigningConfiguration,
    StoreApplication, StoreConnection, StoreRequirement,
)


@admin.register(StoreConnection)
class StoreConnectionAdmin(admin.ModelAdmin):
    list_display = ("organization", "provider", "status", "last_verified")
    list_filter = ("provider", "status")
    # Never surface the credential reference as an editable/searchable secret.
    readonly_fields = ("credential_reference",)


@admin.register(MobileApplication)
class MobileApplicationAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "version", "build_number")


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ("mobile_application", "provider", "version", "state", "readiness")
    list_filter = ("provider", "state")


admin.site.register(StoreApplication)
admin.site.register(MobileBuild)
admin.site.register(SigningConfiguration)
admin.site.register(ReleaseEvent)
admin.site.register(StoreRequirement)
