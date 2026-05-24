from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from .models import Tenant, UploadBatch, SourceRecord, CanonicalRecord, AuditLog
from .normalization import (
    parse_messy_date, normalize_sap_fuel, normalize_utility_electricity, 
    normalize_corporate_travel, process_batch_row
)

class NormalizationTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme Corp")
        self.batch_sap = UploadBatch.objects.create(
            tenant=self.tenant, source_type='SAP_FUEL', filename='sap.csv'
        )
        self.batch_elec = UploadBatch.objects.create(
            tenant=self.tenant, source_type='UTILITY_ELECTRICITY', filename='elec.csv'
        )
        self.batch_travel = UploadBatch.objects.create(
            tenant=self.tenant, source_type='TRAVEL_JSON', filename='travel.json'
        )

    def test_parse_messy_date(self):
        self.assertEqual(parse_messy_date("2026-05-25"), date(2026, 5, 25))
        self.assertEqual(parse_messy_date("05/25/2026"), date(2026, 5, 25))
        self.assertEqual(parse_messy_date("25/05/2026"), date(2026, 5, 25))
        self.assertEqual(parse_messy_date("2026/05/25"), date(2026, 5, 25))
        self.assertEqual(parse_messy_date("May 25, 2026"), date(2026, 5, 25))
        with self.assertRaises(ValueError):
            parse_messy_date("not-a-date")

    def test_sap_fuel_normalization_liters(self):
        raw_row = {
            "Purchase_Date": "2026-05-01",
            "Fuel_Type": "Diesel",
            "Quantity": "500",
            "Unit": "Liters",
            "Vendor": "Shell",
            "Invoice_Number": "INV-1001"
        }
        res = normalize_sap_fuel(raw_row, self.tenant)
        self.assertEqual(res["scope"], "Scope 1")
        self.assertEqual(res["activity_date"], date(2026, 5, 1))
        self.assertEqual(res["original_value"], Decimal("500"))
        self.assertEqual(res["normalized_value"], Decimal("500"))
        self.assertEqual(res["normalized_unit"], "Liters")
        # Diesel factor = 2.68. 500 * 2.68 = 1340
        self.assertEqual(res["co2e_emissions"], Decimal("1340"))
        self.assertFalse(res["suspicious"])

    def test_sap_fuel_normalization_gallons(self):
        raw_row = {
            "Purchase_Date": "05/01/2026",
            "Fuel_Type": "Petrol",
            "Quantity": "100",
            "Unit": "Gallons",
            "Vendor": "BP",
            "Invoice_Number": "INV-1002"
        }
        res = normalize_sap_fuel(raw_row, self.tenant)
        # Petrol EF = 2.31. Gallons conversion = 3.78541
        # Liters = 100 * 3.78541 = 378.541
        # Emissions = 378.541 * 2.31 = 874.4297
        self.assertEqual(res["normalized_unit"], "Liters")
        self.assertAlmostEqual(res["normalized_value"], Decimal("378.5410"), places=4)
        self.assertAlmostEqual(res["co2e_emissions"], Decimal("874.4297"), places=4)
        self.assertFalse(res["suspicious"])

    def test_sap_fuel_suspicious_outlier(self):
        raw_row = {
            "Purchase_Date": "2026-05-01",
            "Fuel_Type": "Diesel",
            "Quantity": "12000", # > 10,000 Liters
            "Unit": "L",
            "Invoice_Number": "INV-1003"
        }
        res = normalize_sap_fuel(raw_row, self.tenant)
        self.assertTrue(res["suspicious"])
        self.assertIn("Unusually high fuel quantity: 12000.00 Liters (>10,000L)", res["suspicious_reasons"])

    def test_sap_fuel_validation_failure(self):
        # Negative quantity
        raw_row = {
            "Purchase_Date": "2026-05-01",
            "Fuel_Type": "Diesel",
            "Quantity": "-10",
            "Unit": "Liters",
            "Invoice_Number": "INV-1004"
        }
        with self.assertRaises(ValueError):
            normalize_sap_fuel(raw_row, self.tenant)

    def test_utility_electricity_normalization(self):
        raw_row = {
            "Billing Period Start": "2026-04-01",
            "Billing Period End": "2026-05-01",
            "Usage kWh": "1500",
            "Account Number": "AC-992",
            "Meter Number": "M-888"
        }
        res = normalize_utility_electricity(raw_row, self.tenant)
        self.assertEqual(res["scope"], "Scope 2")
        self.assertEqual(res["activity_date"], date(2026, 5, 1))
        # EF = 0.40. 1500 * 0.40 = 600
        self.assertEqual(res["co2e_emissions"], Decimal("600"))
        self.assertFalse(res["suspicious"])

    def test_utility_electricity_suspicious_period(self):
        raw_row = {
            "Billing Period Start": "2026-04-01",
            "Billing Period End": "2026-06-01",  # 61 days (outside 15-45 range)
            "Usage kWh": "2000",
            "Account Number": "AC-992",
            "Meter Number": "M-888"
        }
        res = normalize_utility_electricity(raw_row, self.tenant)
        self.assertTrue(res["suspicious"])
        self.assertTrue(any("Billing period of 61 days" in r for r in res["suspicious_reasons"]))

    def test_corporate_travel_normalization(self):
        raw_row = {
            "trip_id": "TRIP-881",
            "employee_id": "EMP-90",
            "departure_airport": "JFK",
            "arrival_airport": "LHR",
            "distance_miles": "3450",
            "class": "Economy",
            "booking_date": "2026-05-15"
        }
        res = normalize_corporate_travel(raw_row, self.tenant)
        self.assertEqual(res["scope"], "Scope 3")
        # Miles to km = 3450 * 1.60934 = 5552.223
        # Economy EF = 0.15. 5552.223 * 0.15 = 832.83345
        self.assertAlmostEqual(res["normalized_value"], Decimal("5552.2230"), places=4)
        self.assertAlmostEqual(res["co2e_emissions"], Decimal("832.8334"), places=4)
        self.assertFalse(res["suspicious"])

    def test_corporate_travel_suspicious_long_flight(self):
        raw_row = {
            "trip_id": "TRIP-882",
            "employee_id": "EMP-90",
            "departure_airport": "JFK",
            "arrival_airport": "SYD",
            "distance_miles": "13000", # > 12,000 miles
            "class": "Business",
            "booking_date": "2026-05-15"
        }
        res = normalize_corporate_travel(raw_row, self.tenant)
        self.assertTrue(res["suspicious"])
        self.assertIn("Unrealistically long flight distance: 13000.00 miles (>12,000 miles)", res["suspicious_reasons"])


class WorkflowAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Globex Corp")
        self.user = User.objects.create_user(username="analyst", password="password123")
        self.client.force_authenticate(user=self.user)
        
        # Seed simple data
        self.batch = UploadBatch.objects.create(
            tenant=self.tenant, source_type='SAP_FUEL', filename='test.csv', status='COMPLETED'
        )
        self.source_record = SourceRecord.objects.create(
            tenant=self.tenant, batch=self.batch, row_number=1,
            raw_payload={
                "Purchase_Date": "2026-05-01",
                "Fuel_Type": "Diesel",
                "Quantity": "1000",
                "Unit": "Liters",
                "Invoice_Number": "INV-ABC-1"
            }
        )
        self.canonical = CanonicalRecord.objects.create(
            tenant=self.tenant,
            source_record=self.source_record,
            batch=self.batch,
            scope="Scope 1",
            category="Fuel Combustion - Diesel",
            activity_date=date(2026, 5, 1),
            original_value=Decimal("1000"),
            original_unit="Liters",
            normalized_value=Decimal("1000"),
            normalized_unit="Liters",
            co2e_emissions=Decimal("2680"),
            approval_status='PENDING',
            is_locked=False
        )

    def test_approval_lock_flow(self):
        # 1. Verify record is not locked
        self.assertFalse(self.canonical.is_locked)
        self.assertEqual(self.canonical.approval_status, 'PENDING')

        # 2. Edit record prior to approval
        url = f"/api/records/{self.canonical.id}/"
        response = self.client.patch(url, {"normalized_value": "900.0"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Refresh and verify emissions recalculated
        self.canonical.refresh_from_db()
        self.assertEqual(self.canonical.normalized_value, Decimal("900.0000"))
        # 900 * 2.68 = 2412
        self.assertEqual(self.canonical.co2e_emissions, Decimal("2412.0000"))
        
        # Verify an EDIT audit log was written
        edit_log = AuditLog.objects.filter(canonical_record=self.canonical, action='EDIT').first()
        self.assertIsNotNone(edit_log)
        self.assertEqual(edit_log.previous_state["normalized_value"], "1000.0000")
        self.assertEqual(edit_log.new_state["normalized_value"], "900.0000")

        # 3. Approve record
        approve_url = f"/api/records/{self.canonical.id}/approve/"
        response = self.client.post(approve_url, {"comment": "Verified with receipt."}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.canonical.refresh_from_db()
        self.assertTrue(self.canonical.is_locked)
        self.assertEqual(self.canonical.approval_status, 'APPROVED')
        
        # Verify APPROVE log
        approve_log = AuditLog.objects.filter(canonical_record=self.canonical, action='APPROVE').first()
        self.assertIsNotNone(approve_log)
        self.assertEqual(approve_log.comments, "Verified with receipt.")

        # 4. Attempt to edit the locked record (should fail)
        response = self.client.patch(url, {"normalized_value": "800.0"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("locked", response.data["error"])

    def test_duplicate_invoices_suspicious(self):
        # Ingest a new row with the same invoice number as self.source_record
        dup_row = {
            "Purchase_Date": "2026-05-02",
            "Fuel_Type": "Diesel",
            "Quantity": "500",
            "Unit": "Liters",
            "Invoice_Number": "INV-ABC-1"  # Same invoice
        }
        
        # Should process but flag suspicious due to duplicate invoice
        res = process_batch_row(self.batch, 2, dup_row)
        self.assertTrue(res.suspicious)
        self.assertTrue(any("Duplicate Invoice Number detected" in r for r in res.suspicious_reasons))
