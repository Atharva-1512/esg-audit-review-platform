from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Tenant, UploadBatch, SourceRecord, CanonicalRecord, AuditLog

class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ['id', 'name', 'created_at']

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class UploadBatchSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = UploadBatch
        fields = [
            'id', 'tenant', 'tenant_name', 'source_type', 'filename', 
            'status', 'error_message', 'created_at', 'created_by_username'
        ]
        read_only_fields = ['id', 'status', 'error_message', 'created_at', 'created_by_username']

class SourceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceRecord
        fields = ['id', 'tenant', 'batch', 'row_number', 'raw_payload', 'status', 'created_at']

class AuditLogSerializer(serializers.ModelSerializer):
    changed_by_username = serializers.CharField(source='changed_by.username', read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            'id', 'tenant', 'canonical_record', 'action', 'changed_by', 
            'changed_by_username', 'timestamp', 'previous_state', 'new_state', 'comments'
        ]

class CanonicalRecordSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    raw_payload = serializers.SerializerMethodField()
    audit_logs = AuditLogSerializer(many=True, read_only=True)

    class Meta:
        model = CanonicalRecord
        fields = [
            'id', 'tenant', 'tenant_name', 'source_record', 'batch', 
            'scope', 'category', 'activity_date', 
            'original_value', 'original_unit', 
            'normalized_value', 'normalized_unit', 
            'co2e_emissions', 'approval_status', 'is_locked', 
            'suspicious', 'suspicious_reasons', 
            'validation_failed', 'failure_reason', 
            'created_at', 'updated_at', 'raw_payload', 'audit_logs'
        ]
        read_only_fields = ['id', 'source_record', 'batch', 'is_locked', 'created_at', 'updated_at', 'raw_payload']

    def get_raw_payload(self, obj):
        if obj.source_record:
            return obj.source_record.raw_payload
        return None
