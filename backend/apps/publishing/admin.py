from django.contrib import admin

from apps.publishing.models import (
    Asset, ContentCollection, ContentItem, CustomDomain, Form, FormSubmission,
    HealthCheck, Lead, PageSeo, PublishVersion, SeoConfig, Website,
)


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = ("subdomain", "project", "site_type", "created_at")


@admin.register(PublishVersion)
class PublishVersionAdmin(admin.ModelAdmin):
    list_display = ("website", "version", "environment", "state", "health", "is_current", "created_at")
    list_filter = ("state", "health", "environment", "host")


@admin.register(CustomDomain)
class CustomDomainAdmin(admin.ModelAdmin):
    list_display = ("hostname", "website", "verification_status", "ssl_status", "provider", "created_at")
    list_filter = ("verification_status", "ssl_status", "provider")


admin.site.register(SeoConfig)


@admin.register(PageSeo)
class PageSeoAdmin(admin.ModelAdmin):
    list_display = ("path", "config", "ai_generated", "approved", "applied")
    list_filter = ("ai_generated", "approved", "applied")


@admin.register(Form)
class FormAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "kind", "active", "created_at")
    list_filter = ("kind", "active")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "website", "status", "source_form", "created_at")
    list_filter = ("status",)


admin.site.register(FormSubmission)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("path", "website", "kind", "size", "width", "height", "created_at")
    list_filter = ("kind",)


@admin.register(HealthCheck)
class HealthCheckAdmin(admin.ModelAdmin):
    list_display = ("website", "status", "response_ms", "checked_at")
    list_filter = ("status",)


@admin.register(ContentCollection)
class ContentCollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "kind", "created_at")
    list_filter = ("kind",)


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    list_display = ("title", "collection", "published", "order")
    list_filter = ("published",)
