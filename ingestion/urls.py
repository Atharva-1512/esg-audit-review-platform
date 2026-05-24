from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TenantViewSet, UploadBatchViewSet, CanonicalRecordViewSet, AuditLogViewSet

router = DefaultRouter()
router.register(r'tenants', TenantViewSet, basename='tenant')
router.register(r'batches', UploadBatchViewSet, basename='batch')
router.register(r'records', CanonicalRecordViewSet, basename='record')
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')

urlpatterns = [
    path('', include(router.urls)),
]
