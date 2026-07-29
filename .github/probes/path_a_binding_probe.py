from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from git_tree_identity import (
    GitProbeError,
    build_tree_manifest,
    manifest_digest,
    manifest_from_bundle,
)


CLEAN = "clean"
READBACK_DIVERGENCE = "readback-divergence"
EXPECTED_MISMATCH_REASON = "REMOTE_IDENTITY_MISMATCH_EXPECTED"


class BindingProbeError(RuntimeError):
    pass


def _git(
    repo: Path,
    args: list[str],
    *,
    failure_kind: str,
) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise BindingProbeError(
            f"{failure_kind}: git {' '.join(args)} failed with "
            f"{result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _log_identity(name: str, value: str) -> None:
    print(f"{name}={value}", flush=True)


def _copy_scoped_http_auth(source: Path, destination: Path) -> None:
    """Copy actions/checkout's local extraheader into the fresh readback repo."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "config",
            "--local",
            "--get-regexp",
            r"^http\..*\.extraheader$",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise BindingProbeError(
            "READBACK_AUTH_CONFIGURATION_FAILURE: could not inspect scoped "
            f"git authentication: {result.stderr.strip()}"
        )
    for line in result.stdout.splitlines():
        key, separator, value = line.partition(" ")
        if not separator:
            raise BindingProbeError(
                "READBACK_AUTH_CONFIGURATION_FAILURE: malformed git extraheader"
            )
        # This subprocess is never echoed; errors also omit its arguments.
        configured = subprocess.run(
            [
                "git",
                "-C",
                str(destination),
                "config",
                "--local",
                "--add",
                key,
                value,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if configured.returncode != 0:
            raise BindingProbeError(
                "READBACK_AUTH_CONFIGURATION_FAILURE: could not install scoped "
                f"git authentication: {configured.stderr.strip()}"
            )


def run_probe(
    *,
    repo: Path,
    bundle: Path,
    remote_url: str,
    remote_branch: str,
    base_commit: str,
    mode: str,
) -> int:
    if mode not in {CLEAN, READBACK_DIVERGENCE}:
        raise BindingProbeError(f"CONFIGURATION_FAILURE: unsupported mode {mode!r}")

    # Identity 1 is derived by importing the attested bundle, not from the
    # checkout that will perform the write.
    _, attested_identity, _ = manifest_from_bundle(
        repo, bundle, base_commit=base_commit
    )
    _log_identity("ATTESTED_IDENTITY", attested_identity)

    head = _git(repo, ["rev-parse", "HEAD"], failure_kind="PREWRITE_GIT_FAILURE")
    prewrite_manifest = build_tree_manifest(repo, head, base_commit=base_commit)
    prewrite_identity = manifest_digest(prewrite_manifest)
    _log_identity("PREWRITE_IDENTITY", prewrite_identity)

    if attested_identity != prewrite_identity:
        raise BindingProbeError(
            "PREWRITE_IDENTITY_MISMATCH: attested bundle and write checkout differ"
        )

    if mode == READBACK_DIVERGENCE:
        marker = repo / "path-a-readback-divergence.txt"
        marker.write_text(
            "deliberate post-verification mutation\n", encoding="utf-8"
        )
        _git(
            repo,
            ["add", "--", marker.name],
            failure_kind="DIVERGENCE_MUTATION_GIT_FAILURE",
        )
        _git(
            repo,
            ["commit", "-m", "Deliberate readback divergence"],
            failure_kind="DIVERGENCE_MUTATION_GIT_FAILURE",
        )

    # A push failure is an operational failure, never a successful probe result.
    _git(
        repo,
        ["push", remote_url, f"HEAD:refs/heads/{remote_branch}"],
        failure_kind="PUSH_OR_AUTHENTICATION_FAILURE",
    )

    # Identity 3 is recomputed in a fresh repository from the remote ref.
    with tempfile.TemporaryDirectory(prefix="path-a-readback-") as tmp:
        readback = Path(tmp) / "repo"
        readback.mkdir()
        _git(readback, ["init"], failure_kind="READBACK_GIT_FAILURE")
        _copy_scoped_http_auth(repo, readback)
        _git(
            readback,
            [
                "fetch",
                "--no-tags",
                remote_url,
                f"refs/heads/{remote_branch}:refs/remotes/origin/probe",
            ],
            failure_kind="READBACK_FETCH_OR_AUTHENTICATION_FAILURE",
        )
        remote_manifest = build_tree_manifest(
            readback, "refs/remotes/origin/probe", base_commit=base_commit
        )
        remote_identity = manifest_digest(remote_manifest)

    _log_identity("REMOTE_IDENTITY", remote_identity)

    if mode == CLEAN:
        if not (
            attested_identity == prewrite_identity == remote_identity
        ):
            raise BindingProbeError(
                "CLEAN_IDENTITY_MISMATCH: all three identities must match"
            )
        print("BINDING_PROBE_RESULT=CLEAN_MATCH", flush=True)
        return 0

    if remote_identity == attested_identity:
        raise BindingProbeError(
            "DIVERGENCE_NOT_OBSERVED: remote unexpectedly matches attested identity"
        )

    print(
        f"BINDING_FAILURE_REASON={EXPECTED_MISMATCH_REASON}",
        flush=True,
    )
    return 42


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--remote-url", required=True)
    parser.add_argument("--remote-branch", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument(
        "--mode",
        choices=(CLEAN, READBACK_DIVERGENCE),
        required=True,
    )
    args = parser.parse_args()

    try:
        return run_probe(
            repo=args.repo.resolve(),
            bundle=args.bundle.resolve(),
            remote_url=args.remote_url,
            remote_branch=args.remote_branch,
            base_commit=args.base_commit,
            mode=args.mode,
        )
    except (BindingProbeError, GitProbeError, OSError) as exc:
        print(f"BINDING_PROBE_OPERATIONAL_FAILURE={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
