---
name: Binding portability probe

on:
  workflow_dispatch:
    inputs:
      mutation:
        description: Deliberate substitution applied to the pending git bundle
        required: true
        default: none
        type: choice
        options:
          - none
          - add
          - remove
          - rename
          - chmod

permissions:
  contents: read

engine:
  id: codex

safe-outputs:
  create-pull-request:
    max: 1
    title-prefix: "[binding-probe] "
    protected-files:
      policy: blocked
    signed-commits: false

  steps:
    - name: Probe platform-observed pending artifact
      env:
        PROBE_MUTATION: ${{ inputs.mutation }}
      run: python .github/probes/safe_outputs_probe.py

timeout-minutes: 20
---

# Binding Portability Probe

Modify only `probe-target.txt` by appending one line containing the current
workflow run ID. Commit the change, then request the `create_pull_request`
safe output.

Do not modify:

- `.github/**`
- `remove-me.txt`
- `rename-me.txt`
- `script.sh`

The purpose of this workflow is to create a real git bundle that the separate
Safe Outputs job will download and inspect before GitHub performs any write.
