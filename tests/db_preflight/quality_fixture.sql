-- Only the disposable PG17 preflight. This fixture is neither product schema nor a migration.
CREATE SCHEMA preflight_quality;
CREATE TABLE preflight_quality.inspection (
    inspection_id uuid PRIMARY KEY,
    store_id text NOT NULL,
    inspector text NOT NULL,
    subject_employee text,
    kind text NOT NULL CHECK (kind IN ('self_check', 'independent')),
    results jsonb NOT NULL
);
CREATE TABLE preflight_quality.review (
    inspection_id uuid PRIMARY KEY REFERENCES preflight_quality.inspection(inspection_id),
    reviewer text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('APPROVED', 'CHANGES_REQUIRED'))
);
