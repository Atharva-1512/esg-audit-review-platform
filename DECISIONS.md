# Architectural & Product Decisions

This document details the engineering and product decisions made during the design of this prototype, and highlights key open questions for the Product Manager (PM).

---

## 1. Resolved Decisions & Rationale

### Field-Level Multi-Tenancy
- **Decision**: Implement multi-tenancy by including a `tenant` Foreign Key on every database table.
- **Rationale**: For an enterprise application, keeping tenant data separate is critical. A field-level isolation strategy is simple to write, highly performant, and maps well to standard Django query filtering. In production, this would be reinforced using Django middleware (e.g., scoping all querysets based on the request tenant) or using PostgreSQL Row Level Security (RLS) to prevent cross-tenant data leaks.

### Preserving Raw Inflow Payload (`JSONField`)
- **Decision**: Store the raw incoming CSV row or JSON record in a `JSONField` (which maps to `JSONB` in PostgreSQL) on the `SourceRecord` model.
- **Rationale**: Data ingestion pipelines inevitably encounter parsing issues, mapping errors, or changing source schemas. Storing the exact incoming raw payload ensures that the system preserves the "origin story" of every record. This allows analysts to view the raw data side-by-side with the normalized representation, facilitating troubleshooting.

### Validation-Failing Rows in the Main Queue
- **Decision**: Create a `CanonicalRecord` entry even when ingestion rows fail critical validation rules (setting `validation_failed=True` and mapping raw values to fallback fields).
- **Rationale**: If a row fails validation (e.g., has a negative value or an unparseable date), dropping it or logging it silently makes it invisible to the business. By creating a placeholder record marked as failed, we display it in the analyst's dashboard. The analyst can then click "Edit", inspect the raw payload on the left, understand what broke, and type in the corrected fields to rescue the row.

### Database Fallback Setup (PostgreSQL & SQLite)
- **Decision**: Configure Django `settings.py` to connect to PostgreSQL if environment variables are present, but fallback to SQLite for local development.
- **Rationale**: While production environments require PostgreSQL for performance, transactional safety, and JSONB index support, requiring developers or evaluators to set up a local PostgreSQL server creates setup friction. This fallback allows the application to run out-of-the-box locally with SQLite, while remaining ready for a PostgreSQL deployment in production.

### Strict Immutability (Audit Lock)
- **Decision**: Set `is_locked = True` immediately when a record's `approval_status` becomes `APPROVED`. The REST API blocks PATCH/PUT operations on locked records.
- **Rationale**: Auditors must be certain that the carbon reports they review cannot be manipulated after validation. Locking the record ensures data integrity. If a change is absolutely necessary, it must undergo a separate administrator unlocking action, writing a distinct audit trail event.

---

## 2. Open Questions for the Product Manager (PM)

### Q1: Versioning and Dynamic Emission Factors
Currently, emission factors (e.g., 2.68 kg CO2e/L for Diesel) are hardcoded based on standard environmental datasets.
- *Product Implications*: Environmental factors change annually (e.g., UK DEFRA or US EPA updates) and electricity grid factors depend heavily on local geography (e.g., power grids in France have lower intensity than in India).
- *Question*: Do we need to build an "Emission Factors Registry" supporting geographical mapping and historical versioning, or should we integrate with third-party APIs (like Electricity Maps) to query real-time factors?

### Q2: Duplicate Handling and Ingestion Auditing
If a user uploads the same CSV file twice, how should the system respond?
- *Product Implications*: Duplicate records skew emission calculations. Currently, we flag subsequent identical invoice numbers or trip IDs as "suspicious", but we still parse them.
- *Question*: Should the system block duplicates entirely at the gate, perform an upsert (overwrite previous records), or prompt the user with a diff comparison during upload?

### Q3: Creator-Approver Separation of Duties (Four-Eyes Principle)
Currently, any authenticated user can edit, approve, or reject records.
- *Product Implications*: Financial and environmental audits often enforce a "separation of duties" where the analyst who uploaded the batch cannot be the one who approves/locks it.
- *Question*: Do we need to enforce a rigid role-based access control (RBAC) model supporting separate "Data Submitter" and "Data Approver" user roles?
