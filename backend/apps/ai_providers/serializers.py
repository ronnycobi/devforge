from rest_framework import serializers

from apps.ai_providers.registry import default_provider_name


class ProviderSerializer(serializers.Serializer):
    """Read-only projection of an AIProvider. Never exposes credentials."""

    name = serializers.CharField()
    available = serializers.SerializerMethodField()
    is_default = serializers.SerializerMethodField()
    default_model = serializers.SerializerMethodField()
    models = serializers.SerializerMethodField()

    def get_available(self, obj):
        return obj.is_available()

    def get_is_default(self, obj):
        return obj.name == default_provider_name()

    def get_default_model(self, obj):
        return obj.default_model()

    def get_models(self, obj):
        return obj.available_models()
