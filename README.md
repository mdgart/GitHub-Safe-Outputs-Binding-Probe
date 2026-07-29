# GitHub Safe Outputs Binding Probe

This is a deliberately small probe for one question:

> Does GitHub Agentic Workflows expose the real pending pull-request artifact to a trusted pre-write step, and can that step stop the write after observing an artifact substitution?

It does **not** implement the final attestor, signing, Faramesh integration, or production evidence format.

## What this probe proves

When run against a real GitHub Agentic Workflow, it checks that:

1. The `safe_outputs` job downloaded the actual git bundle produced by the agent job.
2. A custom `safe-outputs.steps` step can independently inspect that bundle.
3. The step can derive a complete resulting-tree identity from the bundle.
4. The step can observe deliberate add, remove, rename, and chmod substitutions.
5. A mismatch can fail the job before the built-in Safe Outputs handler pushes the branch or creates a pull request.

## What it does not prove

GitHub's built-in handler runs after the custom step and may transform the artifact by:

- rebasing the commit range,
- recreating signed commits,
- resolving temporary IDs,
- linearizing merge commits,
- dropping executable bits in one signed-commit path,
- rejecting or converting unsupported symlink/submodule shapes.

Therefore, inspecting the downloaded bundle proves a useful pre-handler hook exists, but it does **not yet** prove that the exact final artifact GitHub writes is the artifact that was inspected.

That distinction is the company-vs-upstream-feature question.

## Path A: write-owning end-to-end probe

`.github/workflows/path-a-binding-probe.yml` is a conventional, permission-
controlled Actions workflow that owns the GitHub write. Run it manually with
either `clean` or `readback-divergence`.

It logs three independently computed complete-tree identities:

- `ATTESTED_IDENTITY`, imported from the proposed-tree git bundle
- `PREWRITE_IDENTITY`, recomputed from the writer's checked-out tree
- `REMOTE_IDENTITY`, recomputed after fetching the pushed branch into a fresh
  repository

Clean mode succeeds only when all three match. Readback-divergence mode commits
a deliberate tree mutation after pre-write verification and before push, then
fails with exit code 42 after positively observing:

```text
BINDING_FAILURE_REASON=REMOTE_IDENTITY_MISMATCH_EXPECTED
```

Authentication, git, push, and fetch failures use operational-failure messages
and can never produce that security-test result.

## Files

```text
.github/
  probes/
    git_tree_identity.py
    safe_outputs_probe.py
    path_a_binding_probe.py
  workflows/
    binding-portability-probe.md
    path-a-binding-probe.yml
probe/
  git_tree_identity.py
  mutate_bundle.py
  check_compiled_order.py
tests/
  test_tree_identity.py
```

The `.github/probes` scripts are copies used by the live GitHub workflow. The `probe` package is used for local development and tests.

## Local tests

```bash
python -m unittest discover -s tests -v
```

The tests create real git repositories and bundles. They verify that the complete tree identity changes for:

- added files,
- removed files,
- renamed files,
- executable-bit changes.

## Install the live probe in a test repository

Copy these paths into a repository initialized for GitHub Agentic Workflows:

```text
.github/probes/
.github/workflows/binding-portability-probe.md
probe-target.txt
remove-me.txt
rename-me.txt
script.sh
```

Ensure `script.sh` is initially non-executable in git:

```bash
git update-index --chmod=-x script.sh
```

Compile the workflow:

```bash
gh aw compile binding-portability-probe
```

Optionally confirm that the custom probe step is ordered after artifact download but before `Process Safe Outputs`:

```bash
python probe/check_compiled_order.py \
  .github/workflows/binding-portability-probe.lock.yml
```

## Run matrix

Run the workflow five times:

```bash
gh aw run binding-portability-probe -F mutation=none
gh aw run binding-portability-probe -F mutation=add
gh aw run binding-portability-probe -F mutation=remove
gh aw run binding-portability-probe -F mutation=rename
gh aw run binding-portability-probe -F mutation=chmod
```

### Expected result: `mutation=none`

The probe computes the platform-observed bundle identity and exits successfully. The built-in handler may proceed and create a pull request.

### Expected result: mutation attack

For `add`, `remove`, `rename`, or `chmod`:

1. The trusted step computes identity A from the actual bundle on disk.
2. The step deliberately replaces that same pending bundle with B.
3. The step computes identity B from the bundle path the Safe Outputs handler will later consume.
4. The step proves A and B differ.
5. The step exits with code `42`.
6. The Safe Outputs handler must not push or create a PR.

The log must include:

```text
PLATFORM_OBSERVED_BUNDLE=...
IDENTITY_BEFORE=...
IDENTITY_AFTER=...
PROBE_OBSERVED_SUBSTITUTION
```

A green result is not merely a failed job. Confirm that:

- the mutation was positively observed,
- the digest changed for the expected reason,
- no branch was pushed,
- no pull request was created.

## Current decision interpretation

### Strong positive

A trusted pre-write job can inspect the actual pending artifact and block the write, and GitHub exposes a supported hook after all content transformations but before mutation.

### Partial positive

The current likely result: GitHub exposes the downloaded bundle before the handler, but the handler may transform it afterward.

This supports an upstream proposal for a new hook such as:

```text
after_apply_before_push:
  receives:
    - checked-out final tree
    - resolved base
    - exact file modes and contents
  may:
    - fail closed
```

A second supported path is to replace the built-in PR handler with a custom Safe Output job that owns apply, verify, and write. That avoids an invasive fork, but it is a different integration and must be measured honestly as product-owned GitHub write logic.

### Negative

The live workflow cannot access the actual bundle or cannot stop the write before mutation.

## Why the manifest covers the full tree

The identity is not based on agent-declared changed paths.

It recursively enumerates the complete resulting git tree and records:

- raw path bytes,
- git mode,
- object type,
- SHA-256 of blob contents,
- submodule commit identity,
- base commit.

Adding, removing, renaming, changing content, changing symlink target, or changing file mode alters the identity.
