"""Bulk XLSX/CSV Import Center (with formula sanitization & idempotency) and External Catalog API Vault."""
import uuid
from django.conf import settings
from django.db import models
from config.utils import encrypt_field, mask_value, decrypt_field


class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey("sellers.Store", on_delete=models.CASCADE, related_name="import_batches")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    file_name = models.CharField(max_length=180)
    file_type = models.CharField(max_length=12, choices=[("xlsx", "XLSX"), ("csv", "CSV")])
    idempotency_key = models.CharField(max_length=80, unique=True)
    status = models.CharField(
        max_length=24,
        default="PREVIEW",
        choices=[("PREVIEW", "Oldindan ko‘rish"), ("PROCESSING", "Jarayonda"), ("COMPLETED", "Yakunlandi"), ("FAILED", "Xato"), ("CANCELLED", "Bekor qilindi")],
    )
    total_rows = models.PositiveIntegerField(default=0)
    new_count = models.PositiveIntegerField(default=0)
    update_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    error_report_csv = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "import_batches"
        ordering = ["-created_at"]


class ImportRow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    sku = models.CharField(max_length=80, blank=True)
    title = models.CharField(max_length=220, blank=True)
    raw_data = models.JSONField(default=dict)
    normalized_data = models.JSONField(default=dict)
    row_status = models.CharField(
        max_length=20,
        choices=[("NEW", "Yangi"), ("UPDATE", "Yangilanadi"), ("DUPLICATE", "Dublikat"), ("ERROR", "Xato")],
    )
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "import_rows"
        ordering = ["row_number"]


class FieldMapping(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey("sellers.Store", on_delete=models.CASCADE, related_name="field_mappings")
    name = models.CharField(max_length=100)
    mapping_config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "field_mappings"


class ExternalIntegration(models.Model):
    """Encrypted credential vault & SSRF-protected external ERP/API catalog sync (Section 6.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey("sellers.Store", on_delete=models.CASCADE, related_name="external_integrations")
    provider_name = models.CharField(max_length=120)
    endpoint_url = models.URLField()
    api_key_encrypted = models.TextField(blank=True)
    sync_schedule = models.CharField(max_length=40, default="Har 6 soatda")
    field_mapping = models.JSONField(default=dict)
    conflict_resolution = models.CharField(max_length=32, default="SOURCE_PRICE_MODERATED")
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=32, default="IDLE")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "external_integrations"

    def set_api_key(self, raw_key: str):
        self.api_key_encrypted = encrypt_field(raw_key)

    def get_masked_key(self) -> str:
        raw = decrypt_field(self.api_key_encrypted)
        return mask_value(raw, 4, 4) if raw else "********"


class SyncRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration = models.ForeignKey(ExternalIntegration, on_delete=models.CASCADE, related_name="sync_runs")
    status = models.CharField(max_length=24, choices=[("SUCCESS", "Muvaffaqiyatli"), ("PARTIAL", "Qisman"), ("FAILED", "Xato")])
    items_processed = models.PositiveIntegerField(default=0)
    items_queued_moderation = models.PositiveIntegerField(default=0)
    error_log = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sync_runs"
        ordering = ["-started_at"]
