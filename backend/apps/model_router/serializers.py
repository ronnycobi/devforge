from rest_framework import serializers

from apps.ai_providers.registry import registry
from apps.model_router.router import TaskComplexity


class ModelProfileSerializer(serializers.Serializer):
    provider = serializers.CharField()
    model = serializers.CharField()
    tier = serializers.IntegerField()
    context_window = serializers.IntegerField()
    input_cost_per_mtok = serializers.FloatField()
    output_cost_per_mtok = serializers.FloatField()
    speed = serializers.IntegerField()
    available = serializers.SerializerMethodField()

    def get_available(self, obj):
        if obj.provider not in registry:
            return False
        return registry.get(obj.provider).is_available()


class RoutingRequestSerializer(serializers.Serializer):
    complexity = serializers.ChoiceField(
        choices=[c.value for c in TaskComplexity], default=TaskComplexity.MEDIUM.value
    )
    required_context_tokens = serializers.IntegerField(default=0, min_value=0)
    max_cost_per_mtok = serializers.FloatField(required=False, allow_null=True)
    prefer_quality = serializers.BooleanField(default=False)
    preferred_provider = serializers.CharField(required=False, allow_blank=True)
    preferred_model = serializers.CharField(required=False, allow_blank=True)
    allowed_providers = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    task_type = serializers.CharField(required=False, allow_blank=True)


class RoutingDecisionSerializer(serializers.Serializer):
    provider = serializers.CharField()
    model = serializers.CharField()
    reason = serializers.CharField()
    fallbacks = serializers.SerializerMethodField()

    def get_fallbacks(self, obj):
        return [{"provider": p, "model": m} for p, m in obj.fallbacks]
