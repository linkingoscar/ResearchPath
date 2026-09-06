# Distribution and third-party notices

ResearchPath is proprietary software distributed under the root `LICENSE`.
The repository is publicly accessible for inspection, but it is not open
source and grants no additional permission to use, copy, modify, redistribute,
host, or create derivative works. GitHub platform viewing and forking remain
subject to GitHub's Terms of Service. Any broader permission requires prior
written approval from the copyright holder.

The official **PROCESS for R 5.0** macro by Andrew F. Hayes is not included in
this repository. ResearchPath contains an independent estimator and frozen
validation outputs. A researcher may supply an authorized local copy of the
official macro solely to regenerate validation evidence; see
`specs/vendor/SOURCE.md`. Do not add that macro to Git or release artifacts
without written redistribution permission from the copyright holder.

Files under `samples/data/` are deterministic synthetic demonstrations produced
by `scripts/generate-method-demo-data.py`. Validation fixtures that carry a
fixture-specific license retain the notice stored beside that fixture.
Third-party packages remain governed by their own licenses as recorded in the
Python, Node, and R dependency lock files.
