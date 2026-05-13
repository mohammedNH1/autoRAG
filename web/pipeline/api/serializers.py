from rest_framework import serializers


class QueryRequestSerializer(serializers.Serializer):
    question = serializers.CharField(min_length=1, max_length=4000, trim_whitespace=True)


class CitationSerializer(serializers.Serializer):
    document = serializers.CharField()
    page     = serializers.CharField(required=False, allow_blank=True)
    snippet  = serializers.CharField(required=False, allow_blank=True)


class QueryResponseSerializer(serializers.Serializer):
    answer    = serializers.CharField()
    citations = CitationSerializer(many=True, required=False)
