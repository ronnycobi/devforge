from django.contrib import admin

from apps.publishing.models import CustomDomain, PageSeo, PublishVersion, SeoConfig, Website


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
