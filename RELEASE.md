# RTC VarSim v1.0.0 — publication preparation

Prepared on 2026-11-19. Destination: https://github.com/International-Potato-Center-CIP-Rwanda/RTC-VarSim (public). Authenticated Git account: meffovoung; write permission confirmed. The separate Codex GitHub connection is not changed.

## History and approval

The publication checkout starts from the supervisor's existing main commit
06855f0a3ce2bff219372d83b751e4be5f6188eb (Initial commit).
The README begins with the preserved phrase:
Spatial variety best bet location mapping

No code has been sent, and no tag or release has been created. The final manifest must be approved before any publication. No force push, history rewrite or deletion of the supervisor's initial commit is used.

## Strict source-only scope

No data/ directory is present or allowed. No tolerance catalogue, RAB catalogue or overlay, unpublished trial workbook, variety-source inventory, validation table, raster, research PDF, environment, credential or personal path is included. This also excludes the public guide PDF/JSON that earlier private-copy preparation had allowed. Runtime paths in code and fabricated temporary test fixtures are not bundled research data.

The calculation code is unchanged after synchronization and restoration of the reviewed docstrings. Reference tests now construct deliberately fabricated values in temporary directories, so no guide or catalogue is needed to exercise reference precedence, source display, synonyms, non-evaluable entries and missing-reference behavior.

RELEASE_MANIFEST.txt lists the exact files and checksums of the prepared working copy, excluding its own hash. Text-file byte hashes may vary after Git line-ending conversion; regenerate this local review manifest if contents change before the approved commit. Original archive provenance remains in PROVENANCE.json.

## Planned publication after explicit approval

1. Recheck meffovoung authentication, push permission and the remote main head.
2. If main has changed since review, incorporate its new history and review the differences; never force push.
3. Stage only the approved manifest paths and the manifest itself; inspect the staged names/diff.
4. Commit the reviewed RTC VarSim files on main as a descendant of the existing initial commit.
5. Push main normally using the username-qualified remote URL. Do not change any global account or credential.
6. Create and push annotated tag v1.0.0 pointing to the published code commit.
7. Create GitHub release v1.0.0 using the CHANGELOG text; do not attach data or an archive of the research working folder.
8. Verify the public tree, commit parent, tag target and release; report the commit and release URLs.

If authentication or write permission fails, stop for the user. If a repository rule blocks direct main updates, report it instead of bypassing it. The original research folder remains unchanged. No application server or data builder is run during publication checks.

## Validation

Final software test counts, explicit data-dependent skips, sensitive-information scan and source-only manifest verification are recorded in the approval handoff. Synchronization is run before preparing the final tree; after comments and docs are restored, tests and the read-only scan are repeated. No publication is performed by the synchronization script.

## Completed pre-publication checks (2026-11-19)

- Git account meffovoung authenticated and repository push permission confirmed; the separate shared connector remains untouched.
- Synchronization rerun: 48 code/documentation files copied, 20 unlisted source items left uncopied, six protected-file differences reviewed, zero sensitive alerts. Reviewed docstrings were restored only after executable comparisons.
- Tests on the exact public checkout: 103 counted, 99 passed, four explicitly skipped because private integration data is absent, zero failures and zero errors. Synthetic reference-loader tests all pass without any bundled data.
- Read-only sensitive scan: 74 files examined, zero alerts. Occurrences of password, token and key are technical identifiers or scanner vocabulary, not credentials.
- JavaScript syntax and Git whitespace checks passed. Application calculations match the reviewed synchronized baseline; only reference-test fixtures and public-distribution sync restrictions were adapted.
- Source-only manifest has 74 files; data/, all catalogues and trial/validation inputs, variety inventories, PDFs and personal paths are absent. No application server, research-data builder, code commit, push, tag or release was started.
