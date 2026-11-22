# BSV ALL G1 Release Candidate

## Candidate identity

- PR: https://github.com/Ethancao258/bsv-all-platform/pull/38 (Draft; do not merge automatically)
- Verified application source commit: `86271bd0c5c6643a2152c05b7b0550c5d059b5e7`. The final PR head is the source commit plus this delivery-record commit; check PR #38 for the immutable final SHA.
- Validation run: https://github.com/Ethancao258/bsv-all-platform/actions/runs/44985945986 (all 9 jobs passed on the verified source commit). The documentation-only follow-up is revalidated by the CI run attached to its resulting PR head.
- Status: isolated deployment candidate only. No Tencent Cloud host operation, production database access, real payment, or production-data import was performed.

## G1-B — identity, Academy, and three-store POS

Implemented and validated synthetic TR → EMP → approved engagement → published learning → qualification → store/action Grant → approved schedule and employee confirmation → registered device authentication → own-store seats → catalog V9 product `C000001` → unpaid synthetic order. Separate scenarios exercise BSVM, BSVS, and BSVT, including cross-store and revoked-grant/device denials, idempotent replay, and no payment/checkout. HQ page Grant scope selection is bounded by the signed-in account's existing scopes. No canonical seat/layout JSON, permanent IDs, or H default store policy changed.

CI verifies H's default remains BSVT-only; three-store activation requires exact isolated internal-stage flags and the exact BSVM/BSVS/BSVT registry.

## G1-C — operating-chain integrations

The POS/Identity test flow includes a consented, one-use Growth visit proof and rejects a different-store proof. It creates no payment projection or commission. Existing Supply UI is reachable for authorized synthetic BSVT scope; its content says `内部演练`, `暂未启用`, and `中央台账尚未连接`. Supply source A/C/D/E is not configured, so official central supply/receiving facts remain blocked. No fabricated successful receive, payment, refund, or commission is represented as complete.

## G1-D — usable user interfaces

CI runs actual HTTP and Chromium flows at mobile viewport for each of the three synthetic POS stores. It exercises the employee Academy work page and visible entitlement, POS product search/order creation and unpaid feedback, Growth route/store scope, internal Supply unavailable status, and the HQ Grant store-scope selector. Browser screenshots are attached to the `g1-three-store-pos-browser` and `isolated-stage-ui` artifacts in the validation workflow. The stage browser/HTTP artifact is available at https://api.github.com/repos/Ethancao258/bsv-all-platform/actions/artifacts/14740270924/zip and the per-store POS browser artifact at https://api.github.com/repos/Ethancao258/bsv-all-platform/actions/artifacts/14739414692/zip.

The isolated internal stage test entry is `http://127.0.0.1:18760/` only after a separately approved host release and existing SSH tunnel. This CI run does not expose or publish that page publicly.

## G1-E — integrated verification

Validation run `44985945986` passed all nine required jobs on source commit `86271bd0c5c6643a2152c05b7b0550c5d059b5e7`: architecture, BSV1, menu V13.1, Supply V2, V4.1 integration, Customer Growth V4.3, Identity R2, database contract preflight, and Lighthouse internal-stage. Evidence includes Identity/POS/Supply tests: 62 passed, 2 skipped; internal-stage HTTP/browser tests: 7 + 3 + 2 passed; PG17 migration, contract and recovery jobs passed. PostgreSQL recovery reported `AES_GCM_VERIFIED` and POS SQLite `QUICK_CHECK_OK`; live restore was `NOT_RUN`. The release simulation/rollback tests ran in CI; this is not a host backup receipt or real-host rollback proof.

## Release and rollback boundary

Use only the existing deterministic release tool described in `platform/lighthouse/internal-stage/README.md`. After the operator approves the final PR #38 head, the release operator must produce CI proof bound to that exact SHA using `bsvctl.py ci-evidence`, transport it through the already approved channel, inspect host `status`, and obtain explicit isolated-release approval before invoking `bsvctl.py deploy` and `bsvctl.py verify`. The workflow does not run those host commands. If host verification or the separate `acceptance_v41.py --execute-isolated` fails, use the existing `bsvctl.py rollback`; preserve the data/checkpoint and old services 8765/8767. Do not use an unreviewed module list or update production services.

## Remaining blockers

- Real company/employee/course data, CloudBase production access and migration: not authorized or tested.
- Supply authoritative A/C/D/E facts and real receiving: unavailable; UI is intentionally unavailable.
- Real payments, refunds, commissions, customer/member imports, and live business operation: disabled/not tested.
- Lighthouse host deployment, current host config consistency, real HTTP acceptance on 18760–18764, actual checkpoint/restore and rollback: `HOST_NOT_RUN`; no server authorization was given.
- Final operator step: review and approve the exact final PR #38 HEAD for a separate isolated-stage release. This Draft PR is not a production release.
