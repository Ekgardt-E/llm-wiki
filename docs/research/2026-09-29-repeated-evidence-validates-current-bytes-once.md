# Repeated evidence searches bind to current bytes

Researched 2026-09-29. The installed vault has 138 notes in the measured sample.
Correctly finding historical slices is not sufficient for operational acceptance:
the candidate's reference check alone took 224.182 seconds, while the nightly lint
step allows 120 seconds for all structural checks. Different evidence spans and
the prose/claim passes repeatedly searched the same day's same historical digest.

## Path and alternatives

`lint_memory._page_checks` runs reference validation and claim validation. Each
created an `EvidenceResolver`, each reference reread the daily, then historical
resolution enumerated candidate slices again. The graph and sources also identify
archive block validation, ClaimIndex, contradiction checking, and MCP page reads
as consumers. Compile's immutable-byte calls use `resolve_bytes` and remain
unchanged.

Considered raising the nightly deadline, caching by file metadata, adding a
persistent index, or reusing verified searches within the existing resolver.
Raising the deadline leaves duplicated CPU work. Metadata alone cannot prove
unchanged contents. A persistent index adds invalidation and migration work for
data that can be shared locally without a new file or service.

## Current primary sources

- [Python hashlib](https://docs.python.org/3/library/hashlib.html) defines SHA-256
  over the actual byte sequence. Reuse is keyed by the freshly read full-day hash
  and the requested historical digest, not by an mtime assertion.
- [RFC 9111, validation](https://www.rfc-editor.org/rfc/rfc9111.html#section-4.3)
  describes validating a stored representation before reusing it. We apply that
  principle locally; no HTTP cache or HTTP freshness guarantee is introduced.
- [SQLite data_version](https://www.sqlite.org/pragma.html#pragma_data_version)
  describes invalidating cached database-derived state after other connections
  commit. Here Markdown is authoritative, so a database version cannot validate
  its contents; the file's current bytes must do so.

All three independent primary sources were fetched on the research date. This
uses existing hashlib and dictionaries; no dependency version or runtime layout
changes.

## Decision and limits

Each resolver retains the historical parts requested for one current content
digest per daily path. A different full-day digest replaces that day's memoized
parts. Every call still performs the existing stable, no-symlink source read and
hash, and still validates the requested block and byte span. Missing/unreadable
files cannot be satisfied from the memo. A failed search is reusable only for
the same current bytes. The memo lives only as long as its resolver; there is no
cross-process or persistent cache. Lint shares one resolver between the two
checks of a page scope.

The tradeoff is memory proportional to historical parts actually requested in a
resolver's lifetime, replacing repeated hashing with short-lived immutable byte
results. There is no arbitrary new entry-count limit. A changed day drops its old
revision rather than accumulating obsolete versions.

## Evidence and acceptance

The old implementation fails the regression counting searches for two different
spans from the same historical part. The previously separate lint passes also
fail the regression requiring one search for their common evidence. Both pass
after the change. Regressions additionally require append compatibility, rejection
of changed bytes with restored size/mtime, recovery after content restoration,
and refusal after the source is removed.

Measured on the same real notes: reference validation 67.544 seconds and separate
claim validation 33.867 seconds, both without findings, after per-resolver reuse.
The final whole-lint measurement additionally shares those two passes and takes
67.94 seconds within the unchanged 120-second nightly budget. Evidence and claim
findings are zero. Lint still exits 1 with `--fail-on-findings` because 23 sparse
notes and one stale compiled day remain; this is not a claim of a clean vault.
Installation is recorded separately in the private acceptance report. No historical evidence hash or
source content is rewritten and no security check is relaxed.

## Publication retries use the same validated evidence memo

The live post-install compile exposed the same repeated work in publication:
`apply_compile_plan` recreated `ClaimIndex` and its resolver for every `_ApplyPlan`
attempt. Each attempt correctly took a fresh claim-tree manifest and rebuilt the
claims projection, but also searched all unchanged historical evidence again.
An actively updated project page invalidated three attempts before each of two
commits. A temporary derived index reading the real vault measured 44.164 seconds
for a fresh resolver and 0.255 seconds for a second full rebuild using that
resolver; both had zero diagnostics.

The three primary sources above were checked again on 2026-09-29. The selected
change scopes one `ClaimIndex` to one `apply_compile_plan` call. Every attempt
still snapshots the current tree, rereads every page, rebuilds all claims, and
validates the manifest at publication. Only the resolver's content-validated
historical searches survive between attempts and the post-commit rebuild.
Plans without claims still create no claims index. This also applies when a
previously started compile is resumed through its persisted receipts: the call
starts with a fresh index, not persisted cached evidence.

Keeping separate resolvers wastes the measured work. Holding the writer gate
through the expensive assessment blocks capture. Ignoring project updates would
accept stale assessments. Sharing the existing index within a single publication
call avoids all three without a new cache, persistent state, dependency, or limit.
Its memory cost remains bounded by the evidence actually requested for current
daily versions during that call.

The real claim-tree race regression still inserts a claim after assessment and
requires a fresh successful retry. It now additionally records three full index
rebuilds using one resolver. The old code performs those rebuilds with two
resolvers and fails that assertion. The continuously moving tree test must still
refuse publication, and existing source-tamper and no-claims cases remain required.
