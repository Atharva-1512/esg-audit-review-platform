import csv
import json
import io
from datetime import date
from decimal import Decimal
from django.db import transaction
from django.contrib.auth.models import User
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Tenant, UploadBatch, SourceRecord, CanonicalRecord, AuditLog
from .serializers import (
    TenantSerializer, UploadBatchSerializer, SourceRecordSerializer, 
    CanonicalRecordSerializer, AuditLogSerializer
)
from .normalization import process_batch_row, normalize_sap_fuel, normalize_utility_electricity, normalize_corporate_travel

class TenantViewSet(viewsets.ModelViewSet):
    queryset = Tenant.objects.all().order_by('name')
    serializer_class = TenantSerializer

class UploadBatchViewSet(viewsets.ModelViewSet):
    queryset = UploadBatch.objects.all().order_by('-created_at')
    serializer_class = UploadBatchSerializer

    def create(self, request, *args, **kwargs):
        # Overriding create to handle file parsing synchronously
        tenant_id = request.data.get('tenant')
        source_type = request.data.get('source_type')
        file_obj = request.FILES.get('file')
        raw_json_data = request.data.get('json_data')

        if not tenant_id:
            return Response({"error": "tenant is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not source_type:
            return Response({"error": "source_type is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            tenant = Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist:
            return Response({"error": "Tenant not found"}, status=status.HTTP_404_NOT_FOUND)

        filename = file_obj.name if file_obj else "Direct API Upload"

        # Create batch in PENDING
        batch = UploadBatch.objects.create(
            tenant=tenant,
            source_type=source_type,
            filename=filename,
            status='PENDING'
        )

        try:
            rows = []
            if file_obj:
                content = file_obj.read().decode('utf-8-sig')
                if source_type in ['SAP_FUEL', 'UTILITY_ELECTRICITY']:
                    # CSV processing
                    csv_file = io.StringIO(content)
                    reader = csv.DictReader(csv_file)
                    for row in reader:
                        rows.append(row)
                elif source_type == 'TRAVEL_JSON':
                    # JSON processing
                    rows = json.loads(content)
                    if isinstance(rows, dict):
                        rows = [rows]
                else:
                    raise ValueError(f"Unknown source type: {source_type}")
            elif raw_json_data:
                if isinstance(raw_json_data, str):
                    rows = json.loads(raw_json_data)
                elif isinstance(raw_json_data, list):
                    rows = raw_json_data
                elif isinstance(raw_json_data, dict):
                    rows = [raw_json_data]
                else:
                    raise ValueError("Invalid format for json_data")
            else:
                batch.status = 'FAILED'
                batch.error_message = "No file or json_data provided"
                batch.save()
                return Response({"error": "No file or json_data provided"}, status=status.HTTP_400_BAD_REQUEST)

            # Process rows
            batch.status = 'PROCESSING'
            batch.save()

            created_records = []
            with transaction.atomic():
                for idx, row in enumerate(rows, start=1):
                    rec = process_batch_row(batch, idx, row)
                    if rec:
                        created_records.append(rec)

            batch.status = 'COMPLETED'
            batch.save()

            serializer = self.get_serializer(batch)
            return Response({
                "batch": serializer.data,
                "records_created_count": len(created_records)
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            batch.status = 'FAILED'
            batch.error_message = str(e)
            batch.save()
            return Response({
                "error": f"Failed to parse ingestion data: {str(e)}",
                "batch_id": batch.id
            }, status=status.HTTP_400_BAD_REQUEST)

class CanonicalRecordViewSet(viewsets.ModelViewSet):
    queryset = CanonicalRecord.objects.all().order_by('-activity_date', '-created_at')
    serializer_class = CanonicalRecordSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Manual query param filters
        tenant_id = self.request.query_params.get('tenant')
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)

        approval_status = self.request.query_params.get('approval_status')
        if approval_status:
            queryset = queryset.filter(approval_status=approval_status)

        suspicious = self.request.query_params.get('suspicious')
        if suspicious:
            val = suspicious.lower() in ['true', '1']
            queryset = queryset.filter(suspicious=val)

        validation_failed = self.request.query_params.get('validation_failed')
        if validation_failed:
            val = validation_failed.lower() in ['true', '1']
            queryset = queryset.filter(validation_failed=val)

        scope = self.request.query_params.get('scope')
        if scope:
            queryset = queryset.filter(scope=scope)

        source_type = self.request.query_params.get('source_type')
        if source_type:
            queryset = queryset.filter(batch__source_type=source_type)

        return queryset

    def update(self, request, *args, **kwargs):
        # Custom update logic to handle locking, audits, and recalculation
        instance = self.get_object()
        
        if instance.is_locked:
            return Response(
                {"error": "This record is locked and cannot be edited. It has already been approved for audit."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Snapshot old state
        old_state = {
            "scope": instance.scope,
            "category": instance.category,
            "activity_date": str(instance.activity_date),
            "original_value": str(instance.original_value),
            "original_unit": instance.original_unit,
            "normalized_value": str(instance.normalized_value),
            "normalized_unit": instance.normalized_unit,
            "co2e_emissions": str(instance.co2e_emissions),
            "suspicious": instance.suspicious,
            "suspicious_reasons": instance.suspicious_reasons,
            "validation_failed": instance.validation_failed,
            "failure_reason": instance.failure_reason,
        }

        # Modify values from payload
        # Ensure fields can be edited before approval.
        # Recalculate normalized value and emissions if user updates raw values, or let them edit normalized values directly.
        # For full analyst control, we allow them to directly edit both original and normalized fields, but we will
        # re-validate or clear the validation_failed flag if they resolved the issue.
        
        # Capture current user if authenticated
        current_user = request.user if request.user.is_authenticated else None

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # Refresh from db
        instance.refresh_from_db()

        # Recalculate emissions based on changed field if relevant
        recalculated = False
        recalc_reasons = []
        
        # If user changed normalized_value, recalculate co2e
        # Using the standard factors from normalization.py
        ef = Decimal("0.0")
        if instance.scope == "Scope 1":
            fuel_lower = instance.category.lower()
            if "diesel" in fuel_lower:
                ef = Decimal("2.68")
            elif "petrol" in fuel_lower or "gasoline" in fuel_lower:
                ef = Decimal("2.31")
            else:
                ef = Decimal("2.50")
            instance.co2e_emissions = instance.normalized_value * ef
            recalculated = True
        elif instance.scope == "Scope 2":
            ef = Decimal("0.40")
            instance.co2e_emissions = instance.normalized_value * ef
            recalculated = True
        elif instance.scope == "Scope 3":
            category_lower = instance.category.lower()
            if "economy" in category_lower or "econ" in category_lower:
                ef = Decimal("0.15")
            elif "business" in category_lower or "first" in category_lower:
                ef = Decimal("0.29")
            else:
                ef = Decimal("0.20")
            instance.co2e_emissions = instance.normalized_value * ef
            recalculated = True

        # Clear validation failure if edited
        if instance.validation_failed:
            instance.validation_failed = False
            instance.failure_reason = ""
            recalc_reasons.append("Cleared validation_failed status via edit.")
            recalculated = True

        # Recheck suspiciousness rules (simple checks)
        new_susp_reasons = []
        if instance.normalized_value <= 0:
            new_susp_reasons.append("Activity quantity is negative or zero")
        if instance.scope == "Scope 1" and instance.normalized_unit == "Liters" and instance.normalized_value > 10000:
            new_susp_reasons.append(f"Unusually high fuel quantity: {instance.normalized_value:.2f} L")
        if instance.scope == "Scope 2" and instance.normalized_value > 50000:
            new_susp_reasons.append(f"Unusually high electricity usage: {instance.normalized_value:.2f} kWh")
        if instance.scope == "Scope 3" and instance.original_unit == "Miles" and instance.original_value > 12000:
            new_susp_reasons.append(f"Unrealistically long flight distance: {instance.original_value:.2f} miles")

        if instance.suspicious or len(new_susp_reasons) > 0:
            instance.suspicious = len(new_susp_reasons) > 0
            instance.suspicious_reasons = new_susp_reasons
            recalculated = True

        if recalculated:
            instance.save()

        new_state = {
            "scope": instance.scope,
            "category": instance.category,
            "activity_date": str(instance.activity_date),
            "original_value": str(instance.original_value),
            "original_unit": instance.original_unit,
            "normalized_value": str(instance.normalized_value),
            "normalized_unit": instance.normalized_unit,
            "co2e_emissions": str(instance.co2e_emissions),
            "suspicious": instance.suspicious,
            "suspicious_reasons": instance.suspicious_reasons,
            "validation_failed": instance.validation_failed,
            "failure_reason": instance.failure_reason,
        }

        # Write EDIT AuditLog
        comments = request.data.get('comment', 'Manual correction of fields.')
        if recalc_reasons:
            comments += " " + " ".join(recalc_reasons)

        AuditLog.objects.create(
            tenant=instance.tenant,
            canonical_record=instance,
            action='EDIT',
            changed_by=current_user,
            previous_state=old_state,
            new_state=new_state,
            comments=comments
        )

        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        instance = self.get_object()
        if instance.is_locked:
            return Response({"error": "Record is already approved and locked."}, status=status.HTTP_400_BAD_REQUEST)
        
        if instance.validation_failed:
            return Response({"error": "Cannot approve a record that has failed validation. Edit it to fix errors first."}, status=status.HTTP_400_BAD_REQUEST)

        # Snapshot old state
        old_state = {"approval_status": instance.approval_status, "is_locked": instance.is_locked}

        # Approve and lock
        instance.approval_status = 'APPROVED'
        instance.is_locked = True
        instance.save()

        # Snapshot new state
        new_state = {"approval_status": instance.approval_status, "is_locked": instance.is_locked}

        current_user = request.user if request.user.is_authenticated else None
        comment = request.data.get('comment', 'Approved and locked for audit.')

        # AuditLog
        AuditLog.objects.create(
            tenant=instance.tenant,
            canonical_record=instance,
            action='APPROVE',
            changed_by=current_user,
            previous_state=old_state,
            new_state=new_state,
            comments=comment
        )

        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        instance = self.get_object()
        if instance.is_locked:
            return Response({"error": "Record is approved and locked. Cannot reject it now."}, status=status.HTTP_400_BAD_REQUEST)

        # Snapshot old state
        old_state = {"approval_status": instance.approval_status}

        # Reject
        instance.approval_status = 'REJECTED'
        instance.save()

        # Snapshot new state
        new_state = {"approval_status": instance.approval_status}

        current_user = request.user if request.user.is_authenticated else None
        comment = request.data.get('comment', 'Record rejected by analyst.')

        # AuditLog
        AuditLog.objects.create(
            tenant=instance.tenant,
            canonical_record=instance,
            action='REJECT',
            changed_by=current_user,
            previous_state=old_state,
            new_state=new_state,
            comments=comment
        )

        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['get'])
    def audit_history(self, request, pk=None):
        instance = self.get_object()
        logs = instance.audit_logs.all()
        serializer = AuditLogSerializer(logs, many=True)
        return Response(serializer.data)

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all().order_by('-timestamp')
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant_id = self.request.query_params.get('tenant')
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        return queryset
