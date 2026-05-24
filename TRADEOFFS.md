# Architectural Trade-offs & Omissions

To construct a realistic, highly defensible prototype without overengineering, we made deliberate decisions to omit certain complex systems. This document outlines three major omissions and why they were skipped.

---

## 1. Omission of Background Job Queues (Celery/Redis)

- **Omitted System**: Asynchronous background workers for processing ingestion batches.
- **Why We Skipped It**: 
  Setting up background worker orchestration (like Celery, Redis, or django-q) adds significant system complexity, requires running multiple background processes during local development, and complicates deployment.
- **Defensible Alternative**:
  For an internship prototype processing batches of realistic size (e.g. 5–100 rows), processing the files synchronously within the API request thread is highly efficient. The API remains responsive, returning the created records count immediately. We wrapped the ingestion loop inside a Django database transaction (`transaction.atomic`) to ensure that if a fatal parsing error occurs, the batch rolls back safely, keeping the database in a clean state.

---

## 2. Omission of Dynamic Unit Conversion Libraries (e.g., Pint)

- **Omitted System**: An external python library for parsing and converting physical quantities.
- **Why We Skipped It**: 
  Unit libraries like `Pint` or `django-measurement` provide extensive physical quantity support, but they bring steep API learning curves, heavy code footprints, and increase dependency counts.
- **Defensible Alternative**:
  Real-world corporate ESG reporting centers on a very narrow set of activity units:
  - Scope 1: Gallons and Liters.
  - Scope 2: kWh and MWh.
  - Scope 3: Miles and Passenger-Kilometers.
  
  Writing simple, explicit Python functions to standardize these units (e.g., multiplying Gallons by `3.78541` to get Liters) is self-documenting, lightweight, extremely fast, and highly testable. We handle unexpected units by logging a warning in the `suspicious_reasons` field and maintaining a 1:1 mapping, preserving the analyst's ability to review.

---

## 3. Omission of Fine-Grained Role-Based Access Control (RBAC) & OAuth

- **Omitted System**: Authentication servers, token refreshes, and multi-layered user permissions (e.g., separate Auditor, Admin, and Submitter roles).
- **Why We Skipped It**: 
  Building a full RBAC and SSO system takes significant time, requires complex UI routes, and makes local evaluation tedious (requiring creation of multiple users with different privileges to test basic views).
- **Defensible Alternative**:
  We designed the backend database models (`AuditLog`, `UploadBatch`) to link to Django's standard `User` model, demonstrating that the schema is fully audit-capable. We created a mock analyst user session in the React frontend. Any analyst action (editing, approving, rejecting) sends request logs to the backend and records them under the analyst's user ID. This demonstrates security and auditability without the overhead of authentication gatekeeping during evaluation.
