from rest_framework import serializers


class AgentDefinitionSerializer(serializers.Serializer):
    """Read-only projection of an AgentDefinition."""

    key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    capabilities = serializers.SerializerMethodField()

    def get_capabilities(self, obj):
        return obj.capability_values
