import csv
import json
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils.dateparse import parse_date
from .models import Tenant, UploadBatch, SourceRecord, CanonicalRecord, AuditLog

def parse_messy_date(date_str):
    """
    Attempts to parse a variety of messy date string formats.
    Returns a datetime.date object, or raises ValueError if unparseable.
    """
    if not date_str or not isinstance(date_str, str):
        if isinstance(date_str, (datetime, date)):
            return date_str if isinstance(date_str, date) else date_str.date()
        raise ValueError("Date string is empty or invalid type")

    date_str = date_str.strip()
    
    # Try ISO format YYYY-MM-DD
    parsed = parse_date(date_str)
    if parsed:
        return parsed

    # Try common formats
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%b %d, %Y",
        "%d %b %Y",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%y",
        "%d/%m/%y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Could not parse date string: {date_str}")

def to_decimal(val, field_name="Value"):
    """
    Converts a value to Decimal. Raises ValueError if invalid.
    """
    if val is None:
        raise ValueError(f"{field_name} is missing or null")
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    
    val_str = str(val).strip().replace(",", "")
    try:
        return Decimal(val_str)
    except InvalidOperation:
        raise ValueError(f"Invalid decimal format for {field_name}: '{val}'")

def normalize_sap_fuel(raw_row, tenant):
    """
    Normalizes a row from the SAP Fuel procurement CSV.
    Expected keys: Purchase_Date, Fuel_Type, Quantity, Unit, Vendor, Invoice_Number
    """
    # 1. Base details extraction
    purchase_date_raw = raw_row.get("Purchase_Date")
    fuel_type_raw = raw_row.get("Fuel_Type", "").strip()
    quantity_raw = raw_row.get("Quantity")
    unit_raw = raw_row.get("Unit", "").strip()
    invoice_number = raw_row.get("Invoice_Number", "").strip()

    suspicious_reasons = []

    # 2. Check critical missing fields for validation failure
    if not purchase_date_raw:
        raise ValueError("Missing 'Purchase_Date'")
    if not fuel_type_raw:
        raise ValueError("Missing 'Fuel_Type'")
    if quantity_raw is None or str(quantity_raw).strip() == "":
        raise ValueError("Missing 'Quantity'")

    # 3. Parse Date (Failure throws ValueError)
    activity_date = parse_messy_date(str(purchase_date_raw))

    # 4. Parse Quantity (Failure throws ValueError)
    quantity = to_decimal(quantity_raw, "Quantity")
    if quantity < 0:
        raise ValueError("Fuel Quantity cannot be negative")

    # 5. Unit Normalization
    original_unit = unit_raw
    normalized_unit = "Liters"
    unit_norm = original_unit.lower()
    
    # Conversions
    if unit_norm in ["gal", "gals", "gallon", "gallons"]:
        normalized_value = quantity * Decimal("3.78541")
    elif unit_norm in ["l", "liter", "liters", "ltr", "ltrs"]:
        normalized_value = quantity
    elif unit_norm in ["ml", "milliliter", "milliliters"]:
        normalized_value = quantity / Decimal("1000")
        suspicious_reasons.append(f"Small unit '{original_unit}' normalized to Liters")
    else:
        # Unknown unit: parse quantity but flag suspicious and keep 1:1
        normalized_value = quantity
        normalized_unit = original_unit or "Unknown"
        suspicious_reasons.append(f"Unknown unit '{original_unit}' - fallback direct mapping used")

    # 6. Scope mapping & CO2e calculation
    # SAP fuel is Scope 1 (Direct combustion)
    scope = "Scope 1"
    category = f"Fuel Combustion - {fuel_type_raw}"
    
    # Emission Factors (kg CO2e per Liter)
    fuel_lower = fuel_type_raw.lower()
    if "diesel" in fuel_lower:
        ef = Decimal("2.68")  # Diesel emission factor
    elif "petrol" in fuel_lower or "gasoline" in fuel_lower:
        ef = Decimal("2.31")  # Petrol emission factor
    else:
        ef = Decimal("2.50")  # Default fallback factor
        suspicious_reasons.append(f"Unknown fuel type '{fuel_type_raw}' - using fallback emission factor 2.50 kg CO2e/L")

    # Emissions = Liters * EF
    if normalized_unit == "Liters":
        co2e_emissions = normalized_value * ef
    else:
        co2e_emissions = normalized_value * ef  # fallback
        suspicious_reasons.append("CO2e calculation applied directly to non-standard normalized unit")

    # 7. Additional suspiciousness checks
    if quantity == 0:
        suspicious_reasons.append("Activity quantity is exactly zero")
    if normalized_unit == "Liters" and normalized_value > Decimal("10000"):
        suspicious_reasons.append(f"Unusually high fuel quantity: {normalized_value:.2f} Liters (>10,000L)")
    if not invoice_number:
        suspicious_reasons.append("Missing Invoice Number")
    else:
        # Check for duplicate invoices
        dup_exists = CanonicalRecord.objects.filter(
            tenant=tenant,
            source_record__raw_payload__Invoice_Number=invoice_number
        ).exclude(approval_status='REJECTED').exists()
        if dup_exists:
            suspicious_reasons.append(f"Duplicate Invoice Number detected: '{invoice_number}'")

    return {
        "scope": scope,
        "category": category,
        "activity_date": activity_date,
        "original_value": quantity,
        "original_unit": original_unit or "Unknown",
        "normalized_value": normalized_value.quantize(Decimal("1.0000")),
        "normalized_unit": normalized_unit,
        "co2e_emissions": co2e_emissions.quantize(Decimal("1.0000")),
        "suspicious": len(suspicious_reasons) > 0,
        "suspicious_reasons": suspicious_reasons,
    }

def normalize_utility_electricity(raw_row, tenant):
    """
    Normalizes a row from the Utility Electricity portal export.
    Expected keys: Billing Period Start, Billing Period End, Usage kWh, Account Number, Meter Number
    """
    # 1. Base details extraction
    start_date_raw = raw_row.get("Billing Period Start")
    end_date_raw = raw_row.get("Billing Period End")
    usage_raw = raw_row.get("Usage kWh")
    account_number = raw_row.get("Account Number", "").strip()
    meter_number = raw_row.get("Meter Number", "").strip()

    suspicious_reasons = []

    # 2. Check critical missing fields for validation failure
    if not end_date_raw:
        raise ValueError("Missing 'Billing Period End'")
    if usage_raw is None or str(usage_raw).strip() == "":
        raise ValueError("Missing 'Usage kWh'")

    # 3. Parse Dates
    activity_date = parse_messy_date(str(end_date_raw))
    start_date = None
    if start_date_raw:
        try:
            start_date = parse_messy_date(str(start_date_raw))
        except ValueError:
            suspicious_reasons.append(f"Could not parse Billing Period Start date: '{start_date_raw}'")

    # 4. Parse Usage
    usage = to_decimal(usage_raw, "Usage kWh")
    if usage < 0:
        raise ValueError("Electricity usage cannot be negative")

    # 5. Unit Normalization (Standardize to kWh)
    # We look for "Usage kWh" or a separate Unit field. Since the portal export has "Usage kWh" header, standard unit is kWh.
    # If the user included unit in the value (e.g. "1200 MWh"), we convert it.
    original_unit = "kWh"
    normalized_value = usage
    normalized_unit = "kWh"

    # 6. Scope mapping & CO2e calculation
    # Purchased electricity is Scope 2 (Indirect emissions)
    scope = "Scope 2"
    category = "Purchased Electricity - Grid Consumption"
    
    # Location-based grid emission factor (e.g. 0.4 kg CO2e / kWh)
    ef = Decimal("0.40")
    co2e_emissions = normalized_value * ef

    # 7. Additional suspiciousness checks
    if usage == 0:
        suspicious_reasons.append("Activity usage is exactly zero")
    if normalized_value > Decimal("50000"):
        suspicious_reasons.append(f"Unusually high electricity usage: {normalized_value:.2f} kWh (>50,000 kWh)")
    if not account_number:
        suspicious_reasons.append("Missing Account Number")
    if not meter_number:
        suspicious_reasons.append("Missing Meter Number")
    
    if start_date and activity_date:
        days = (activity_date - start_date).days
        if days < 15 or days > 45:
            suspicious_reasons.append(f"Billing period of {days} days is outside typical monthly range (15-45 days)")
        if activity_date < start_date:
            raise ValueError(f"Billing Period End ({activity_date}) is before Billing Period Start ({start_date})")

    return {
        "scope": scope,
        "category": category,
        "activity_date": activity_date,
        "original_value": usage,
        "original_unit": original_unit,
        "normalized_value": normalized_value.quantize(Decimal("1.0000")),
        "normalized_unit": normalized_unit,
        "co2e_emissions": co2e_emissions.quantize(Decimal("1.0000")),
        "suspicious": len(suspicious_reasons) > 0,
        "suspicious_reasons": suspicious_reasons,
    }

def normalize_corporate_travel(raw_row, tenant):
    """
    Normalizes a row from Corporate Travel JSON API.
    Expected keys: trip_id, employee_id, departure_airport, arrival_airport, distance_miles, class, booking_date
    """
    # 1. Base details extraction
    trip_id = raw_row.get("trip_id")
    booking_date_raw = raw_row.get("booking_date")
    distance_raw = raw_row.get("distance_miles")
    flight_class = raw_row.get("class", "").strip()
    dep_airport = raw_row.get("departure_airport", "").strip()
    arr_airport = raw_row.get("arrival_airport", "").strip()

    suspicious_reasons = []

    # 2. Check critical missing fields
    if not trip_id:
        raise ValueError("Missing 'trip_id'")
    if not booking_date_raw:
        raise ValueError("Missing 'booking_date'")
    if distance_raw is None or str(distance_raw).strip() == "":
        raise ValueError("Missing 'distance_miles'")

    # 3. Parse Date
    activity_date = parse_messy_date(str(booking_date_raw))

    # 4. Parse Distance
    distance = to_decimal(distance_raw, "distance_miles")
    if distance < 0:
        raise ValueError("Flight distance cannot be negative")

    # 5. Unit Normalization (Convert Miles to Passenger-km)
    original_unit = "Miles"
    normalized_unit = "Passenger-km"
    normalized_value = distance * Decimal("1.60934")

    # 6. Scope mapping & CO2e calculation
    # Flight travel is Scope 3 (Category 6: Business Travel)
    scope = "Scope 3"
    category = f"Business Travel - Flights ({flight_class or 'Unknown Class'})"
    
    # Class-based emission factor (kg CO2e / km)
    class_norm = flight_class.lower()
    if class_norm in ["economy", "econ", "y"]:
        ef = Decimal("0.15")
    elif class_norm in ["business", "biz", "c", "first", "f"]:
        ef = Decimal("0.29")
    else:
        ef = Decimal("0.20")  # fallback standard factor
        suspicious_reasons.append(f"Unknown flight class '{flight_class}' - fell back to default emission factor 0.20 kg CO2e/km")

    co2e_emissions = normalized_value * ef

    # 7. Additional suspiciousness checks
    if distance == 0:
        suspicious_reasons.append("Activity distance is exactly zero")
    if distance > 12000:
        suspicious_reasons.append(f"Unrealistically long flight distance: {distance:.2f} miles (>12,000 miles)")
    if not dep_airport or not arr_airport:
        suspicious_reasons.append("Missing departure or arrival airport code")
    else:
        # Simple airport code check (must look like IATA code: 3 alphabetical letters)
        airport_regex = re.compile(r"^[A-Za-z]{3}$")
        if not airport_regex.match(dep_airport) or not airport_regex.match(arr_airport):
            suspicious_reasons.append(f"Invalid airport code format: '{dep_airport}' -> '{arr_airport}'")

    # Check for duplicate trip_id in database
    dup_exists = CanonicalRecord.objects.filter(
        tenant=tenant,
        source_record__raw_payload__trip_id=trip_id
    ).exclude(approval_status='REJECTED').exists()
    if dup_exists:
        suspicious_reasons.append(f"Duplicate trip_id detected: '{trip_id}'")

    return {
        "scope": scope,
        "category": category,
        "activity_date": activity_date,
        "original_value": distance,
        "original_unit": original_unit,
        "normalized_value": normalized_value.quantize(Decimal("1.0000")),
        "normalized_unit": normalized_unit,
        "co2e_emissions": co2e_emissions.quantize(Decimal("1.0000")),
        "suspicious": len(suspicious_reasons) > 0,
        "suspicious_reasons": suspicious_reasons,
    }

def process_batch_row(batch, row_number, raw_row):
    """
    Parses and normalizes a single row in an upload batch.
    Creates a SourceRecord, runs normalization, and creates a CanonicalRecord.
    Catches errors and marks validation_failed on CanonicalRecord.
    Returns the created CanonicalRecord (or None if critical failure occurred in SourceRecord creation).
    """
    tenant = batch.tenant
    
    # 1. Create SourceRecord to preserve the raw payload
    source_rec = SourceRecord.objects.create(
        tenant=tenant,
        batch=batch,
        row_number=row_number,
        raw_payload=raw_row,
        status='UNPROCESSED'
    )

    try:
        # 2. Normalize based on batch source type
        if batch.source_type == 'SAP_FUEL':
            norm_data = normalize_sap_fuel(raw_row, tenant)
        elif batch.source_type == 'UTILITY_ELECTRICITY':
            norm_data = normalize_utility_electricity(raw_row, tenant)
        elif batch.source_type == 'TRAVEL_JSON':
            norm_data = normalize_corporate_travel(raw_row, tenant)
        else:
            raise ValueError(f"Unknown batch source type: {batch.source_type}")

        # 3. Create successful CanonicalRecord
        canonical = CanonicalRecord.objects.create(
            tenant=tenant,
            source_record=source_rec,
            batch=batch,
            scope=norm_data["scope"],
            category=norm_data["category"],
            activity_date=norm_data["activity_date"],
            original_value=norm_data["original_value"],
            original_unit=norm_data["original_unit"],
            normalized_value=norm_data["normalized_value"],
            normalized_unit=norm_data["normalized_unit"],
            co2e_emissions=norm_data["co2e_emissions"],
            approval_status='PENDING',
            suspicious=norm_data["suspicious"],
            suspicious_reasons=norm_data["suspicious_reasons"],
            validation_failed=False
        )
        
        # Write creation audit log
        AuditLog.objects.create(
            tenant=tenant,
            canonical_record=canonical,
            action='CREATE',
            new_state={
                "scope": canonical.scope,
                "category": canonical.category,
                "activity_date": str(canonical.activity_date),
                "normalized_value": str(canonical.normalized_value),
                "normalized_unit": canonical.normalized_unit,
                "co2e_emissions": str(canonical.co2e_emissions),
                "suspicious": canonical.suspicious,
                "suspicious_reasons": canonical.suspicious_reasons
            },
            comments="Record ingested and normalized automatically."
        )

        source_rec.status = 'NORMALIZED'
        source_rec.save()
        return canonical

    except Exception as e:
        # In case of validation failure, create a CanonicalRecord representing the failed ingestion
        # so that it appears in the review queue and the user can see/fix the raw payload.
        error_msg = str(e)
        
        # Try to extract partial fields if available for dashboard display
        # Default fallback values for required fields in DB
        scope = "Scope 1" if batch.source_type == 'SAP_FUEL' else ("Scope 2" if batch.source_type == 'UTILITY_ELECTRICITY' else "Scope 3")
        category = f"Failed Ingestion - {batch.source_type}"
        
        # Try to parse a date, or use current date as fallback
        activity_date = date.today()
        for k in ["Purchase_Date", "Billing Period End", "booking_date"]:
            if raw_row.get(k):
                try:
                    activity_date = parse_messy_date(str(raw_row.get(k)))
                    break
                except ValueError:
                    pass

        # Quantity values fallback
        orig_val = Decimal("0.0")
        for k in ["Quantity", "Usage kWh", "distance_miles"]:
            if raw_row.get(k) is not None:
                try:
                    orig_val = to_decimal(raw_row.get(k))
                    break
                except ValueError:
                    pass
        
        orig_unit = raw_row.get("Unit") or raw_row.get("unit") or "Unknown"
        if batch.source_type == 'UTILITY_ELECTRICITY':
            orig_unit = "kWh"
        elif batch.source_type == 'TRAVEL_JSON':
            orig_unit = "Miles"

        canonical = CanonicalRecord.objects.create(
            tenant=tenant,
            source_record=source_rec,
            batch=batch,
            scope=scope,
            category=category,
            activity_date=activity_date,
            original_value=orig_val,
            original_unit=str(orig_unit),
            normalized_value=Decimal("0.0"),
            normalized_unit=str(orig_unit),
            co2e_emissions=Decimal("0.0"),
            approval_status='PENDING',
            validation_failed=True,
            failure_reason=error_msg
        )

        # Write audit log for failed record
        AuditLog.objects.create(
            tenant=tenant,
            canonical_record=canonical,
            action='CREATE',
            new_state={
                "validation_failed": True,
                "failure_reason": error_msg
            },
            comments=f"Failed normalization: {error_msg}"
        )

        source_rec.status = 'VALIDATION_FAILED'
        source_rec.save()
        return canonical

def process_batch(batch_id):
    """
    Processes an entire UploadBatch row-by-row.
    """
    try:
        batch = UploadBatch.objects.get(pk=batch_id)
    except UploadBatch.DoesNotExist:
        return False

    batch.status = 'PROCESSING'
    batch.save()

    try:
        raw_content = None
        # Retrieve the raw data based on how it's stored.
        # For simplicity in testing/prototype, we can support reading from raw file or payload field.
        # If the batch has a file uploaded, we read it. Since we will write APIs to accept uploads, 
        # we will handle files. Let's see if we read from batch.raw_file. Let's support reading a file path or a string.
        # Let's assume we pass the file contents in the request, or we read a text file.
        # Let's write a simple router.
        
        # We can implement batch processing under a database transaction
        with transaction.atomic():
            # If batch has a filename or a local file in Django, let's open it.
            # But let's check what we get.
            pass

    except Exception as e:
        batch.status = 'FAILED'
        batch.error_message = str(e)
        batch.save()
        return False
