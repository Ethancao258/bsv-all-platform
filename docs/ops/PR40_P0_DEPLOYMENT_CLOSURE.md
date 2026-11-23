# PR #40 P0 deployment closure

## Scope

This delivery closes the cross-version isolated deployment and WorkBuddy V2.2 catalog-read path. It does not claim the whole company has moved to one physical database. `bsv_all_prod` is the future authoritative business database; identity PostgreSQL and POS SQLite remain compatibility stores in this P0. CloudBase is not a dependency.

## Cross-version failures addressed

- Preserve the f6d8 identity archive contract (`identity-A-*`, authenticated source `A`) while making the catalog archive use the fully attested candidate release, with a distinct `catalog-*` name and authenticated `catalog` source label.
- Pin the catalog backup generator release SHA and Git tree in checkpoint evidence. Recovery verifies that precise managed release, including after code rollback.
- Reject catalog checkpoints unless the archive is authenticated PostgreSQL format 2, bound to the loopback `bsv_all_prod` importer, and matches its SHA-256.
- Keep catalog role-membership validation directional and least-privileged. `bsv_catalog_reader` has no outgoing membership grants; the runtime role receives the approved reader memberships.
- Run service-user release traversal checks with a safe child-process working directory. Do not relax the private package or release directory modes.
- Preserve any prior release, database, HBA edits, roles, credentials, backup, or failed-work directory. Unknown existing state remains a fail-closed preflight condition.

## Data and employee interface acceptance

The existing employee POS catalog page remains the UI. Its PostgreSQL API acceptance verifies an authenticated employee can search and read C000001, its recipe, the P000003 → R000048 production link, M000001 with purchase price withheld, and K000001. Anonymous catalog reads are denied. The UI/API reads do not approve raw rows for sale and do not use payment. POS order/seat writes remain SQLite compatibility writes.

GitHub CI now runs a Chromium employee-page flow against real PostgreSQL 17 test data, verifies the page labels PostgreSQL as its source, renders recipe/steps/locator, and confirms catalog browsing creates no order. The identity PG17 job creates a catalog archive with the restricted importer owner, verifies AEAD metadata, restores into a separate disposable PG17 database, queries the restored row, and rejects ciphertext tampering.

## State and evidence

| Gate | State |
|---|---|
| Code | Implemented on PR #40 branch; use this file's containing commit as the exact source revision. |
| Local targeted release tests | 7 passed; Python syntax compilation and `git diff --check` passed. |
| Local PostgreSQL 17 restore | NOT_RUN: the managed execution filesystem returned ENOSPC while creating disposable databases. This is not reported as a pass. |
| GitHub CI | Check the exact commit's PR checks; all workflow jobs must finish successfully before applying the package. |
| Real Lighthouse deploy/import/browser | NOT_RUN by Codex; no TAT/SSH host execution capability is attached. The latest owner-provided host evidence says old release f6d8 is healthy after automatic rollback; it predates this candidate. |
| Real catalog backup restore and code rollback | NOT_RUN on Lighthouse. CI verifies archive/restore behavior on disposable PG17; the TAT script performs an isolated restore rehearsal and preserves data. |

## TAT boundary

The generated private package pins the exact PR commit, CI proof, and WorkBuddy ZIP hash. Upload that package to `/home/ubuntu`, then invoke the included script once as root with `--approve-isolated <exact SHA>`. The script performs read-only preflight, verifies the package and source, uses the managed release tool, imports only into isolated `bsv_all_prod` as `IMPORTED_RAW`, verifies employee HTTP reads and encrypted backup recovery, and stops on drift. It never removes previous directories/backups or changes CloudBase, payments, identity history, or 8765/8767. If a post-switch gate fails, it calls the existing managed rollback and retains catalog data and evidence.

Required TAT settings: user `root`; working directory `/home/ubuntu`; timeout `3600` seconds. Host/browser results are pending the owner-run TAT action and must be recorded separately from CI.
