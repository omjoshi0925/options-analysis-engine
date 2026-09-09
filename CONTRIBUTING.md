# Contributing

Run before every commit: `scripts/check.sh` (ruff, pytest, manifest check).

Commits use conventional prefixes (feat, fix, docs, chore, ci, test) and carry no Co-Authored-By or other trailers.

Results live only under docs/results/ and every new artifact gets a manifest entry with its SHA-256 (`python docs/results/build_manifest.py`). A number that is not in the manifest is not reported anywhere.

docs/RESEARCH_PLAN.md is pre-registered: nothing above section 10 is edited after 2026-09-08. Changes are appended as dated amendments in section 10 and echoed in docs/NOTEBOOK.md.

Tagged studies (study-v1, later study-v2-locked) are never moved. Corrections to a frozen report are separate commits after the tag.
