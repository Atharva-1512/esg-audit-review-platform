import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction
from ingestion.models import Tenant, UploadBatch, SourceRecord, CanonicalRecord, AuditLog
from ingestion.normalization import process_batch_row

class Command(BaseCommand):
    help = "Seed the database with realistic ESG ingestion data, including messy formats, validation failures, and suspicious rows."

    def handle(self, *args, **options):
        self.stdout.write("Clearing existing data...")
        AuditLog.objects.all().delete()
        CanonicalRecord.objects.all().delete()
        SourceRecord.objects.all().delete()
        UploadBatch.objects.all().delete()
        
        # Don't delete Tenant if it exists or clear all
        Tenant.objects.all().delete()
        
        self.stdout.write("Creating default Tenant and User...")
        tenant = Tenant.objects.create(name="BreatheESG Enterprises")
        
        # Create analyst user
        if not User.objects.filter(username="analyst").exists():
            User.objects.create_superuser(username="analyst", email="analyst@breatheesg.com", password="password123")
            self.stdout.write("Created superuser 'analyst' with password 'password123'")
        else:
            analyst = User.objects.get(username="analyst")
            analyst.set_password("password123")
            analyst.save()

        # Seed data
        self.seed_sap_fuel(tenant)
        self.seed_utility_electricity(tenant)
        self.seed_corporate_travel(tenant)

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))

    def seed_sap_fuel(self, tenant):
        self.stdout.write("Seeding SAP Fuel CSV batch...")
        batch = UploadBatch.objects.create(
            tenant=tenant,
            source_type='SAP_FUEL',
            filename='sap_fuel_procurement_may_2026.csv',
            status='PENDING'
        )

        rows = [
            # 1. Valid Liters
            {
                "Purchase_Date": "2026-05-01",
                "Fuel_Type": "Diesel",
                "Quantity": "1200.50",
                "Unit": "Liters",
                "Vendor": "Shell Commercial",
                "Invoice_Number": "INV-FUEL-101"
            },
            # 2. Valid Gallons (messy date, needs conversion)
            {
                "Purchase_Date": "05/12/2026",
                "Fuel_Type": "Petrol",
                "Quantity": "250.0",
                "Unit": "Gallons",
                "Vendor": "Chevron Corp",
                "Invoice_Number": "INV-FUEL-102"
            },
            # 3. Suspicious - Outlier quantity (> 10000 L)
            {
                "Purchase_Date": "2026-05-18",
                "Fuel_Type": "Diesel",
                "Quantity": "15000",
                "Unit": "Liters",
                "Vendor": "BP Fueling Services",
                "Invoice_Number": "INV-FUEL-103"
            },
            # 4. Suspicious - Unknown Fuel Type
            {
                "Purchase_Date": "2026/05/20",
                "Fuel_Type": "Hydrogen H2",
                "Quantity": "400.0",
                "Unit": "Liters",
                "Vendor": "CleanEnergy Co",
                "Invoice_Number": "INV-FUEL-104"
            },
            # 5. Validation Failure - Negative Quantity
            {
                "Purchase_Date": "2026-05-22",
                "Fuel_Type": "Diesel",
                "Quantity": "-150",
                "Unit": "Liters",
                "Vendor": "Shell Commercial",
                "Invoice_Number": "INV-FUEL-105"
            },
            # 6. Validation Failure - Malformed Date
            {
                "Purchase_Date": "not-a-valid-date",
                "Fuel_Type": "Diesel",
                "Quantity": "800.0",
                "Unit": "Liters",
                "Vendor": "BP Fueling Services",
                "Invoice_Number": "INV-FUEL-106"
            },
            # 7. Suspicious - Duplicate Invoice Number
            {
                "Purchase_Date": "2026-05-24",
                "Fuel_Type": "Diesel",
                "Quantity": "750.0",
                "Unit": "Liters",
                "Vendor": "Shell Commercial",
                "Invoice_Number": "INV-FUEL-101" # Duplicate of Row 1
            }
        ]

        batch.status = 'PROCESSING'
        batch.save()
        
        for idx, row in enumerate(rows, start=1):
            process_batch_row(batch, idx, row)

        batch.status = 'COMPLETED'
        batch.save()

    def seed_utility_electricity(self, tenant):
        self.stdout.write("Seeding Utility Electricity CSV batch...")
        batch = UploadBatch.objects.create(
            tenant=tenant,
            source_type='UTILITY_ELECTRICITY',
            filename='utility_electric_billing_q2_2026.csv',
            status='PENDING'
        )

        rows = [
            # 1. Valid electricity
            {
                "Billing Period Start": "2026-04-01",
                "Billing Period End": "2026-05-01",
                "Usage kWh": "4200.0",
                "Account Number": "AC-ELEC-8812",
                "Meter Number": "M-9911-A"
            },
            # 2. Messy dates, valid electricity
            {
                "Billing Period Start": "04/01/2026",
                "Billing Period End": "05-01-2026",
                "Usage kWh": "3800.25",
                "Account Number": "AC-ELEC-8812",
                "Meter Number": "M-9911-A"
            },
            # 3. Suspicious - Outlier consumption (>50k kWh)
            {
                "Billing Period Start": "2026-04-01",
                "Billing Period End": "2026-05-01",
                "Usage kWh": "65000",
                "Account Number": "AC-ELEC-8812",
                "Meter Number": "M-9911-B"
            },
            # 4. Suspicious - Billing Period too long (65 days)
            {
                "Billing Period Start": "2026-03-01",
                "Billing Period End": "2026-05-05",
                "Usage kWh": "8900",
                "Account Number": "AC-ELEC-8812",
                "Meter Number": "M-9911-A"
            },
            # 5. Suspicious - Missing Account & Meter Number
            {
                "Billing Period Start": "2026-04-01",
                "Billing Period End": "2026-05-01",
                "Usage kWh": "2100",
                "Account Number": "",
                "Meter Number": ""
            },
            # 6. Validation Failure - End date before Start date
            {
                "Billing Period Start": "2026-05-01",
                "Billing Period End": "2026-04-15",
                "Usage kWh": "1400",
                "Account Number": "AC-ELEC-8812",
                "Meter Number": "M-9911-A"
            }
        ]

        batch.status = 'PROCESSING'
        batch.save()
        
        for idx, row in enumerate(rows, start=1):
            process_batch_row(batch, idx, row)

        batch.status = 'COMPLETED'
        batch.save()

    def seed_corporate_travel(self, tenant):
        self.stdout.write("Seeding Corporate Travel JSON batch...")
        batch = UploadBatch.objects.create(
            tenant=tenant,
            source_type='TRAVEL_JSON',
            filename='corp_travel_trips_ytd.json',
            status='PENDING'
        )

        rows = [
            # 1. Valid Economy Flight
            {
                "trip_id": "T-10001",
                "employee_id": "EMP-41",
                "departure_airport": "JFK",
                "arrival_airport": "LHR",
                "distance_miles": "3450",
                "class": "Economy",
                "booking_date": "2026-05-02"
            },
            # 2. Valid Business Flight
            {
                "trip_id": "T-10002",
                "employee_id": "EMP-92",
                "departure_airport": "SFO",
                "arrival_airport": "NRT",
                "distance_miles": "5150",
                "class": "Business",
                "booking_date": "05/04/2026"
            },
            # 3. Suspicious - Outlier Flight distance (> 12,000 miles)
            {
                "trip_id": "T-10003",
                "employee_id": "EMP-102",
                "departure_airport": "SIN",
                "arrival_airport": "JFK",
                "distance_miles": "14500",
                "class": "First",
                "booking_date": "2026-05-08"
            },
            # 4. Suspicious - Invalid Airport Code formats
            {
                "trip_id": "T-10004",
                "employee_id": "EMP-12",
                "departure_airport": "JFK-NY",
                "arrival_airport": "LHR-LDN",
                "distance_miles": "3450",
                "class": "Economy",
                "booking_date": "2026-05-10"
            },
            # 5. Validation Failure - Missing trip_id
            {
                "trip_id": "",
                "employee_id": "EMP-41",
                "departure_airport": "JFK",
                "arrival_airport": "LHR",
                "distance_miles": "3450",
                "class": "Economy",
                "booking_date": "2026-05-12"
            },
            # 6. Suspicious - Duplicate Trip ID
            {
                "trip_id": "T-10001", # Duplicate of Row 1
                "employee_id": "EMP-23",
                "departure_airport": "CDG",
                "arrival_airport": "FRA",
                "distance_miles": "280",
                "class": "Economy",
                "booking_date": "2026-05-14"
            }
        ]

        batch.status = 'PROCESSING'
        batch.save()
        
        for idx, row in enumerate(rows, start=1):
            process_batch_row(batch, idx, row)

        batch.status = 'COMPLETED'
        batch.save()
