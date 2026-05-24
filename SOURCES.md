# Data Sources & Ingestion Streams

This document details the three source formats modeled in this assignment, lists the seeded sample data, explains their real-world characteristics, and outlines what would fail in a production environment.

---

## 1. SAP Fuel Procurement (Scope 1)

### Real-World Context
In large enterprises, fuel purchases for company vehicles, logistics, and onsite backup generators are tracked in procurement systems like SAP Ariba or SAP S/4HANA. Finance departments export monthly transaction ledgers as CSV files.

### Seeded CSV Format & Header Mapping
- **Columns**: `Purchase_Date`, `Fuel_Type`, `Quantity`, `Unit`, `Vendor`, `Invoice_Number`

### Realistic Sample Rows (from `seed_data.py`)
1. **Normal Liters**: `2026-05-01, Diesel, 1200.50, Liters, Shell Commercial, INV-FUEL-101`
   - *Why realistic*: Standard, clean transaction ledger.
2. **Messy Gallons**: `05/12/2026, Petrol, 250.0, Gallons, Chevron Corp, INV-FUEL-102`
   - *Why realistic*: ERP exports from US branches use US Customary units (Gallons) and US date formats (`MM/DD/YYYY`), whereas EMEA branches use Liters and ISO dates.
3. **Suspicious Outlier**: `2026-05-18, Diesel, 15000, Liters, BP Fueling Services, INV-FUEL-103`
   - *Why realistic*: Purchasing 15,000 liters of diesel in a single transaction exceeds typical fuel tank limits, indicating potential data entry error (e.g. extra zero added).
4. **Suspicious Duplicate**: `2026-05-24, Diesel, 750.0, Liters, Shell Commercial, INV-FUEL-101`
   - *Why realistic*: Re-submitting an invoice (`INV-FUEL-101`) already processed is a common source of double-counting in carbon accounting.
5. **Validation Failure**: `2026-05-22, Diesel, -150, Liters, Shell Commercial, INV-FUEL-105`
   - *Why realistic*: Finance logs sometimes contain negative lines representing invoice reversals or refunds, which must be filtered or handled separately in ESG engines.
6. **Validation Failure (Malformed Date)**: `not-a-valid-date, Diesel, 800, Liters, BP, INV-FUEL-106`
   - *Why realistic*: Dirty exports containing footer notes or summary totals inside date cells.

### Production Vulnerabilities (SAP Fuel)
- **Column Header Drift**: If an SAP system update changes the header name from `Purchase_Date` to `Invoice Date`, our schema mapping will crash.
- **Large Files Timeout**: Synchronous parsing of a 500,000-line CSV file inside an API thread will trigger web server gateway timeouts. Production requires chunked streaming or background workers.

---

## 2. Utility Electricity Portal Export (Scope 2)

### Real-World Context
Organizations download monthly billing and energy consumption reports directly from utility provider portals (e.g., PG&E, Con Edison, National Grid) in CSV formats.

### Seeded CSV Format & Header Mapping
- **Columns**: `Billing Period Start`, `Billing Period End`, `Usage kWh`, `Account Number`, `Meter Number`

### Realistic Sample Rows (from `seed_data.py`)
1. **Normal Billing**: `2026-04-01, 2026-05-01, 4200.0, AC-ELEC-8812, M-9911-A`
   - *Why realistic*: Standard monthly consumption cycle (30 days) and standard meter details.
2. **Messy Date Formats**: `04/01/2026, 05-01-2026, 3800.25, AC-ELEC-8812, M-9911-A`
   - *Why realistic*: Start uses slash-dates and End uses dash-dates depending on provider formatting.
3. **Suspicious Billing Cycle**: `2026-03-01, 2026-05-05, 8900, AC-ELEC-8812, M-9911-A`
   - *Why realistic*: A billing period of 65 days is highly abnormal and suggests a missing intermediate bill or overlapping readings.
4. **Suspicious Missing Fields**: `2026-04-01, 2026-05-01, 2100, , `
   - *Why realistic*: Missing account and meter numbers make it impossible to audit utility consumption back to physical locations.
5. **Validation Failure**: `2026-05-01, 2026-04-15, 1400, AC-ELEC-8812, M-9911-A`
   - *Why realistic*: End date before start date is a logical impossibility representing a corrupt CSV generation.

### Production Vulnerabilities (Utility Electricity)
- **Multi-Facility Mapping**: Large enterprises manage hundreds of offices. A real-world utility CSV must map specific meters (`M-9911-A`) to specific facilities. If a facility does not exist, ingestion must trigger mapping requests.
- **Estimated Readings**: Utility bills often use "Estimated" rather than "Actual" readings. Production systems must track whether a billing row is actual or estimated.

---

## 3. Corporate Travel JSON (Scope 3)

### Real-World Context
Corporate flights are ingested via webhook API integrations from corporate travel management providers like Navan (formerly TripActions), SAP Concur, or corporate travel agencies.

### Seeded JSON Format & Key Mapping
- **JSON Object Keys**: `trip_id`, `employee_id`, `departure_airport`, `arrival_airport`, `distance_miles`, `class`, `booking_date`

### Realistic Sample Rows (from `seed_data.py`)
1. **Normal Economy**:
   ```json
   { "trip_id": "T-10001", "departure_airport": "JFK", "arrival_airport": "LHR", "distance_miles": "3450", "class": "Economy", "booking_date": "2026-05-02" }
   ```
2. **Normal Business**:
   ```json
   { "trip_id": "T-10002", "departure_airport": "SFO", "arrival_airport": "NRT", "distance_miles": "5150", "class": "Business", "booking_date": "05/04/2026" }
   ```
3. **Suspicious Outlier Distance**:
   ```json
   { "trip_id": "T-10003", "departure_airport": "SIN", "arrival_airport": "JFK", "distance_miles": "14500", "class": "First", "booking_date": "2026-05-08" }
   ```
   - *Why realistic*: 14,500 miles exceeds the flight distance of any commercial airline route, indicating bad API inputs.
4. **Suspicious Invalid Airport Format**:
   ```json
   { "trip_id": "T-10004", "departure_airport": "JFK-NY", "arrival_airport": "LHR-LDN", "distance_miles": "3450", "class": "Economy", "booking_date": "2026-05-10" }
   ```
   - *Why realistic*: System outputting airport name description rather than the standard 3-letter IATA code.
5. **Validation Failure (Missing ID)**:
   ```json
   { "trip_id": "", "departure_airport": "JFK", "arrival_airport": "LHR", "distance_miles": "3450", "class": "Economy", "booking_date": "2026-05-12" }
   ```

### Production Vulnerabilities (Corporate Travel)
- **Haversine Distance Verification**: Direct travel APIs rarely provide `distance_miles`. Real-world engines ingest airport codes and calculate distances using Great-Circle (Haversine) formulas.
- **Multi-segment Flights**: Real business travel consists of layovers (e.g. SFO -> ORD -> LHR). Ingestion pipelines must break bookings down into distinct flight segments to accurately compute emissions.
