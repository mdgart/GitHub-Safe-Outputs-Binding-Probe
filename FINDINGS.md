# Preliminary source-level finding

## Supported pre-handler hook: yes

Current GitHub Agentic Workflows source builds the consolidated Safe Outputs job in this order:

1. setup,
2. download agent output and patch/bundle artifact,
3. check out the target repository,
4. execute user-provided `safe-outputs.steps`,
5. execute built-in Safe Outputs handlers.

That is sufficient to inspect the actual downloaded bundle and fail the job before the handler begins.

## Supported final-artifact hook: not found

The built-in create-pull-request handler subsequently applies the bundle or patch and may:

- rebase commits,
- synthesize signed commits,
- replace temporary IDs in file contents,
- linearize merge commits,
- alter or reject unsupported file modes.

The current public extension points place custom steps before the handler or custom jobs before/after the consolidated job. They do not clearly expose a supported hook after the handler has produced its final local tree but before it pushes.

## Preliminary interpretation

The platform appears to support:

> Bind evidence to the raw bundle GitHub downloaded.

It does not yet clearly support:

> Bind evidence to GitHub's independently observed final post-transformation tree immediately before the write.

The live probe in this package confirms the first statement. If it does, the next useful work is likely an upstream GitHub proposal for a fail-closed `after-apply-before-push` verifier hook, not a standalone workaround that trusts an agent-supplied digest.

## Supported fallback worth testing

GitHub also supports custom Safe Output jobs that run as separate permission-controlled jobs after agent completion. A custom job could download the Actions artifact, apply the bundle, compute the final tree identity, verify the certificate, and perform the GitHub write itself. That may achieve hard binding without forking `gh-aw`, but it replaces the built-in `create-pull-request` handler and therefore must be evaluated as integration code, not as a native verifier hook.
