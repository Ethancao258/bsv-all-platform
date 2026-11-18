-- BSV ALL identity candidate PostgreSQL 17 schema, generated locally.
-- NOT APPROVED FOR CLOUDBASE / PRODUCTION EXECUTION.
-- Before any live migration: CloudBase G0 read-only schema/permissions audit, G1 backup restore
-- evidence, official platform migration plan, approval and rollback rehearsal.
-- Isolated authentication test-only table is intentionally EXCLUDED.


CREATE OR REPLACE FUNCTION bsv_identity_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'BSV historical record is immutable: %', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql
;


CREATE OR REPLACE FUNCTION bsv_identity_reject_tr_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'TR permanent identity cannot be deleted';
    END IF;
    IF NEW.tr_code IS DISTINCT FROM OLD.tr_code THEN
        RAISE EXCEPTION 'TR permanent identity cannot change';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
;


CREATE TABLE bsv_identity_people (
	tr_code VARCHAR(7) NOT NULL,
	display_label VARCHAR(80),
	status VARCHAR(12) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	version INTEGER NOT NULL,
	PRIMARY KEY (tr_code),
	CONSTRAINT people_status_ck CHECK (status IN ('active','suspended','tombstone'))
)

;


CREATE TRIGGER bsv_identity_tr_permanent BEFORE UPDATE OR DELETE ON bsv_identity_people
FOR EACH ROW EXECUTE FUNCTION bsv_identity_reject_tr_change()
;


CREATE TABLE bsv_identity_code_allocator (
	id SERIAL NOT NULL,
	next_index INTEGER NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT capacity_ck CHECK (next_index >= 0 AND next_index <= 239976)
)

;


CREATE TABLE bsv_identity_auth_sessions (
	token_hash VARCHAR(64) NOT NULL,
	subject VARCHAR(128) NOT NULL,
	csrf_hash VARCHAR(64) NOT NULL,
	issued_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (token_hash)
)

;

CREATE INDEX ix_bsv_identity_auth_sessions_subject ON bsv_identity_auth_sessions (subject);


CREATE TABLE bsv_identity_audit_events (
	id VARCHAR(36) NOT NULL,
	event_type VARCHAR(80) NOT NULL,
	legal_entity_id VARCHAR(80),
	target_tr VARCHAR(7),
	actor_subject VARCHAR(128) NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	effective_at TIMESTAMP WITH TIME ZONE,
	reason VARCHAR(500) NOT NULL,
	details JSON NOT NULL,
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_bsv_identity_audit_events_legal_entity_id ON bsv_identity_audit_events (legal_entity_id);

CREATE INDEX ix_bsv_identity_audit_events_target_tr ON bsv_identity_audit_events (target_tr);

CREATE INDEX idx_audit_time ON bsv_identity_audit_events (occurred_at);

CREATE TRIGGER bsv_identity_block_update_delete BEFORE UPDATE OR DELETE ON bsv_identity_audit_events FOR EACH ROW EXECUTE FUNCTION bsv_identity_reject_mutation();


CREATE TABLE bsv_identity_stage_issuances (
	id VARCHAR(36) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	stage VARCHAR(3) NOT NULL,
	issued_at TIMESTAMP WITH TIME ZONE NOT NULL,
	issued_by VARCHAR(128) NOT NULL,
	approval_ref VARCHAR(128) NOT NULL,
	reason VARCHAR(500) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT one_stage_ever_per_person UNIQUE (tr_code, stage),
	CONSTRAINT stage_allowed_ck CHECK (stage IN ('TR','EMP','BM')),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT
)

;

CREATE TRIGGER bsv_identity_block_update_delete BEFORE UPDATE OR DELETE ON bsv_identity_stage_issuances FOR EACH ROW EXECUTE FUNCTION bsv_identity_reject_mutation();


CREATE TABLE bsv_identity_auth_links (
	id VARCHAR(36) NOT NULL,
	auth_subject_id VARCHAR(128) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	provider VARCHAR(25) NOT NULL,
	linked_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (auth_subject_id),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT
)

;

CREATE INDEX idx_authlink_tr ON bsv_identity_auth_links (tr_code);


CREATE TABLE bsv_identity_registration_requests (
	id VARCHAR(36) NOT NULL,
	subject VARCHAR(128) NOT NULL,
	requested_legal_entity_id VARCHAR(80) NOT NULL,
	idempotency_key VARCHAR(80) NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	display_label VARCHAR(80) NOT NULL,
	proof_digest VARCHAR(64),
	consent_version VARCHAR(30) NOT NULL,
	status VARCHAR(20) NOT NULL,
	verified_by VARCHAR(128),
	verification_reason VARCHAR(500),
	separate_person_confirmed BOOLEAN NOT NULL,
	approved_by VARCHAR(128),
	approved_tr_code VARCHAR(7),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT reg_idempotence_uk UNIQUE (subject, idempotency_key),
	FOREIGN KEY(approved_tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT
)

;

CREATE INDEX idx_reg_proof ON bsv_identity_registration_requests (proof_digest);

CREATE INDEX idx_reg_status ON bsv_identity_registration_requests (status);

CREATE INDEX ix_bsv_identity_registration_requests_subject ON bsv_identity_registration_requests (subject);

CREATE INDEX ix_bsv_identity_registration_requests_requested_legal_entity_id ON bsv_identity_registration_requests (requested_legal_entity_id);


CREATE TABLE bsv_identity_engagements (
	id VARCHAR(36) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	legal_entity_id VARCHAR(80) NOT NULL,
	type VARCHAR(25) NOT NULL,
	effective_from TIMESTAMP WITH TIME ZONE NOT NULL,
	effective_to TIMESTAMP WITH TIME ZONE,
	evidence_ref VARCHAR(160) NOT NULL,
	status VARCHAR(16) NOT NULL,
	created_by VARCHAR(128) NOT NULL,
	approved_by VARCHAR(128),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT eng_type_ck CHECK (type IN ('employee','part_time','contractor','partner')),
	CONSTRAINT eng_status_ck CHECK (status IN ('pending','active','ended','rejected')),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT
)

;

CREATE INDEX idx_eng_active ON bsv_identity_engagements (tr_code, legal_entity_id, status);


CREATE TABLE bsv_identity_qualification_links (
	id VARCHAR(36) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	qualification_code VARCHAR(60) NOT NULL,
	learning_credential_id VARCHAR(128) NOT NULL,
	source_evidence_ref VARCHAR(160) NOT NULL,
	effective_from TIMESTAMP WITH TIME ZONE NOT NULL,
	effective_to TIMESTAMP WITH TIME ZONE,
	status VARCHAR(14) NOT NULL,
	verified_by VARCHAR(128) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT,
	UNIQUE (learning_credential_id)
)

;

CREATE INDEX idx_qualification_tr ON bsv_identity_qualification_links (tr_code, qualification_code);


CREATE TABLE bsv_identity_stage_requests (
	id VARCHAR(36) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	stage VARCHAR(3) NOT NULL,
	legal_entity_id VARCHAR(80) NOT NULL,
	requested_by VARCHAR(128) NOT NULL,
	reason VARCHAR(500) NOT NULL,
	status VARCHAR(14) NOT NULL,
	decided_by VARCHAR(128),
	decided_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT req_stage_ck CHECK (stage IN ('EMP','BM')),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT
)

;


CREATE TABLE bsv_identity_grants (
	id VARCHAR(36) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	legal_entity_id VARCHAR(80) NOT NULL,
	store_id VARCHAR(80),
	role VARCHAR(25) NOT NULL,
	action VARCHAR(80) NOT NULL,
	required_qualification VARCHAR(60),
	valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
	valid_to TIMESTAMP WITH TIME ZONE,
	status VARCHAR(14) NOT NULL,
	requested_by VARCHAR(128) NOT NULL,
	approved_by VARCHAR(128),
	approved_at TIMESTAMP WITH TIME ZONE,
	revoked_by VARCHAR(128),
	revoked_at TIMESTAMP WITH TIME ZONE,
	reason VARCHAR(500) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT grant_role_ck CHECK (role IN ('staff','manager','hq')),
	CONSTRAINT grant_status_ck CHECK (status IN ('pending','active','rejected','revoked')),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT
)

;

CREATE INDEX idx_grant_scope ON bsv_identity_grants (tr_code, legal_entity_id, store_id, action, status);


CREATE TABLE bsv_identity_legacy_aliases (
	id VARCHAR(36) NOT NULL,
	legal_entity_id VARCHAR(80) NOT NULL,
	source_system VARCHAR(80) NOT NULL,
	legacy_value VARCHAR(200) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	approved_by VARCHAR(128) NOT NULL,
	evidence_ref VARCHAR(160) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT legacy_alias_unique UNIQUE (legal_entity_id, source_system, legacy_value),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT
)

;


CREATE TABLE bsv_identity_auth_recovery_requests (
	id VARCHAR(36) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	legal_entity_id VARCHAR(80) NOT NULL,
	new_auth_subject_id VARCHAR(128) NOT NULL,
	previous_auth_subject_id VARCHAR(128),
	evidence_ref VARCHAR(160) NOT NULL,
	requested_by VARCHAR(128) NOT NULL,
	status VARCHAR(15) NOT NULL,
	approved_by VARCHAR(128),
	approved_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT recovery_status_ck CHECK (status IN ('pending','approved','rejected')),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT
)

;


CREATE TABLE bsv_identity_privacy_requests (
	id VARCHAR(36) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	legal_entity_id VARCHAR(80) NOT NULL,
	requested_by VARCHAR(128) NOT NULL,
	evidence_ref VARCHAR(160) NOT NULL,
	reason VARCHAR(500) NOT NULL,
	status VARCHAR(15) NOT NULL,
	decided_by VARCHAR(128),
	decided_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT privacy_req_status_ck CHECK (status IN ('pending','approved','rejected')),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT
)

;


CREATE TABLE bsv_identity_bm_appointments (
	id VARCHAR(36) NOT NULL,
	tr_code VARCHAR(7) NOT NULL,
	legal_entity_id VARCHAR(80) NOT NULL,
	stage_request_id VARCHAR(36) NOT NULL,
	valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
	valid_to TIMESTAMP WITH TIME ZONE,
	status VARCHAR(14) NOT NULL,
	issued_by VARCHAR(128) NOT NULL,
	revoked_by VARCHAR(128),
	revoked_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(tr_code) REFERENCES bsv_identity_people (tr_code) ON DELETE RESTRICT,
	UNIQUE (stage_request_id),
	FOREIGN KEY(stage_request_id) REFERENCES bsv_identity_stage_requests (id)
)

;
