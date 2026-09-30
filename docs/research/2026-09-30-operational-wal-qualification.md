# Qualified WAL for adopted coordination databases

Date: 2026-09-30. Status: preparation authorized; live migration not qualified.

The installed CPython 3.14.6 uses SQLite 3.53.1. The adopted coordinator and
queue currently use DELETE journaling. A held read snapshot deterministically
prevents a DELETE writer's commit; the same transaction commits in WAL, while
both snapshots retain their original values and integrity checks succeed.
This is a concurrency mechanism, not proof that every historical hook timeout
has this cause. Full integrity scans remain a separate cost.

## Primary sources and alternatives

- SQLite: https://sqlite.org/wal.html — simultaneous readers and one writer,
  local shared memory, persistent sidecars and checkpoint costs. FULL preserves
  commit durability; NORMAL is not selected. The WAL-reset fix is required:
  3.51.3 onward, or documented 3.44.6 / 3.50.7 backports.
- APSW: https://rogerbinns.github.io/apsw/tips.html — independent wrapper guidance
  recommends WAL and explicit contention handling. Adopting APSW itself would
  add a dependency without removing the surrounding admission requirements.
- Python: https://docs.python.org/3.14/library/sqlite3.html — explicit transaction
  management and the online backup API. Existing stdlib connections can retain
  their interface and produce consistent snapshots while writes continue.
- Installed release: https://sqlite.org/releaselog/3_53_1.html.

Retaining DELETE avoids sidecars but keeps reader/writer commit interference.
Increasing hook timeouts only tolerates longer blocking and does not remove it.
Removing integrity checks weakens corruption detection and is rejected. A new
persistent writer service adds lifecycle complexity and is not needed for this
local two-database case. WAL/FULL is selected for qualification, retaining one
writer, canonical ownership, full validation, and existing default checkpoints.
Long readers can still retain WAL pages; WAL is not a cure for CPU or writer
contention. No arbitrary new limits or checkpoint tuning are introduced.

## Data path and acceptance

Native adapters admit evidence through coordinator/queue factories, adoption
validation, shared SQLite openers, canonical ownership, transaction receipts,
and Markdown projection. Existing openers force DELETE even on an already-WAL
database. Ordinary opens must preserve the persisted mode, accepting WAL only
for the two recognized v3 application headers on a fixed SQLite runtime.
Other operational databases retain their existing DELETE contract. Sidecars
must be private regular files under the runtime root; validation must not open
and close an extra descriptor that would drop SQLite advisory locks.

The adoption manifest pins the observed mode. A qualified offline migration
must coordinate both modes and that manifest under exclusive canonical
admission, with durable interruption recovery and verified rollback. Old
processes capable of forcing DELETE must be stopped before cutover. Online
backup, staged restore, corruption rejection, held-reader writes, and already
started/new captures must pass. Public CI alone does not satisfy this contract.

Codebase Memory identified shared opener consumers in ownership, transactions,
queue, claims, generation catalog, telemetry, doctor, repair and MCP readers.
Backup uses sqlite3.Connection.backup rather than copying active database bytes.
Graph edges include heuristic false positives; SQL, sidecars and manifest
bindings must additionally be checked against source and runtime evidence.

## Local qualification evidence

The five regression cases failed on bea86752: ordinary writers downgraded WAL,
read-only opens rejected it, and an unrelated database was silently downgraded.
The mode-preserving candidate passes held-reader commits for both protocol IDs,
unsafe-version rejection, foreign-contract rejection, sidecar symlink/permissions/
hardlink refusal, and online backup of an uncheckpointed committed value.
The related durability/adoption/backup/structure suite passed 199 tests with
three existing platform skips before the final four hardlink cases were added.
Lizard reports no CCN above five in either changed Python file; AST inspection
confirms at most two if statements and at most two nested loop/if levels in every
changed function. These are candidate checks, not an installed migration proof.

A further dependency is confirmed: the adopted manifest pins journal_mode=delete;
its schema digest is also bound by the migration descriptor and both tombstones.
Changing only the database or expanding the JSON schema would invalidate existing
adoption. Their coordinated transition, failure recovery, full adopted-vault
backup/restore, and restarting old mode-forcing processes remain required before
installation/cutover. No live database has been switched by this change.
