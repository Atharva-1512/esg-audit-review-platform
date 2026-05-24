import uuid
from django.db import models
from django.contrib.auth.models import User

class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class UploadBatch(models.Model):
    SOURCE_TYPES = [
        ('SAP_FUEL', 'SAP Fuel CSV Export'),
        ('UTILITY_ELECTRICITY', 'Utility Electricity Portal Export'),
        ('TRAVEL_JSON', 'Corporate Travel JSON API/File'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending Processing'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='batches')
    source_type = models.CharField(max_length=50, choices=SOURCE_TYPES)
    filename = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.source_type} Batch ({self.id}) - {self.status}"

class SourceRecord(models.Model):
    STATUS_CHOICES = [
        ('UNPROCESSED', 'Unprocessed'),
        ('NORMALIZED', 'Normalized'),
        ('VALIDATION_FAILED', 'Validation Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='source_records')
    batch = models.ForeignKey(UploadBatch, on_delete=models.CASCADE, related_name='source_records')
    row_number = models.IntegerField()
    raw_payload = models.JSONField(help_text="Stores the exact raw source record/row")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UNPROCESSED')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['row_number']

    def __str__(self):
        return f"Row {self.row_number} - Batch {self.batch_id}"

class CanonicalRecord(models.Model):
    SCOPE_CHOICES = [
        ('Scope 1', 'Scope 1 - Direct Emissions'),
        ('Scope 2', 'Scope 2 - Indirect Emissions (Electricity)'),
        ('Scope 3', 'Scope 3 - Other Indirect Emissions (Travel, etc.)'),
    ]

    APPROVAL_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved & Locked'),
        ('REJECTED', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='canonical_records')
    source_record = models.OneToOneField(SourceRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='canonical_record')
    batch = models.ForeignKey(UploadBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='canonical_records')
    
    # Normalization details
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES)
    category = models.CharField(max_length=100, help_text="e.g. Diesel, Petrol, Electricity, Business Travel Flight")
    activity_date = models.DateField(help_text="Normalized activity date")
    
    original_value = models.DecimalField(max_digits=18, decimal_places=4)
    original_unit = models.CharField(max_length=50)
    
    normalized_value = models.DecimalField(max_digits=18, decimal_places=4)
    normalized_unit = models.CharField(max_length=50)
    
    # Calculated Impact
    co2e_emissions = models.DecimalField(max_digits=18, decimal_places=4, help_text="Emissions in kg CO2e")
    
    # Workflow
    approval_status = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='PENDING')
    is_locked = models.BooleanField(default=False, help_text="Locked for audit after approval")
    
    # Quality flags
    suspicious = models.BooleanField(default=False)
    suspicious_reasons = models.JSONField(default=list, blank=True, help_text="Array of reasons why flagged suspicious")
    
    validation_failed = models.BooleanField(default=False)
    failure_reason = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.category} ({self.activity_date}) - {self.normalized_value} {self.normalized_unit}"

class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('CREATE', 'Created Record'),
        ('EDIT', 'Edited Fields'),
        ('APPROVE', 'Approved & Locked'),
        ('REJECT', 'Rejected Record'),
        ('UNLOCK', 'Unlocked Record (Admin only)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='audit_logs')
    canonical_record = models.ForeignKey(CanonicalRecord, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # Before/After snapshots
    previous_state = models.JSONField(default=dict, blank=True)
    new_state = models.JSONField(default=dict, blank=True)
    
    comments = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} on {self.canonical_record_id} at {self.timestamp}"
