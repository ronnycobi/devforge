from django.contrib import admin

from apps.skills.models import Skill


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "scope", "organization", "project", "enabled")
    list_filter = ("scope", "enabled")
