from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class GitProbeError(RuntimeError):
    pass


def _run_git(
    repo: Path,
    args: list[str],
    *,
    check: bool = True,
    text: bool = False,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=text,
    )
    if check and result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise GitProbeError(
            f"git {' '.join(args)} failed with {result.returncode}: {stderr}"
        )
    return result


def resolve_bundle_head(bundle_path: Path) -> tuple[str, str]:
    result = subprocess.run(
        ["git", "bundle", "list-heads", str(bundle_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise GitProbeError(
            "git bundle list-heads failed: "
            + result.stderr.decode("utf-8", "replace")
        )

    heads: list[tuple[str, str]] = []
    head_fallback: tuple[str, str] | None = None
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        oid = parts[0].decode("ascii")
        ref = parts[1].decode("utf-8", "strict")
        if ref.startswith("refs/heads/"):
            heads.append((oid, ref))
        elif ref == "HEAD":
            head_fallback = (oid, ref)

    if len(heads) == 1:
        return heads[0]
    if not heads and head_fallback:
        return head_fallback
    raise GitProbeError(
        f"Expected exactly one branch head or HEAD in bundle, found {len(heads)} branch heads"
    )


def fetch_bundle_to_ref(
    repo: Path,
    bundle_path: Path,
    *,
    destination_ref: str | None = None,
) -> str:
    _, source_ref = resolve_bundle_head(bundle_path)
    destination_ref = destination_ref or f"refs/attestation/{uuid.uuid4().hex}"

    result = _run_git(
        repo,
        ["fetch", str(bundle_path), f"{source_ref}:{destination_ref}"],
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise GitProbeError(
            "Could not fetch bundle into the checkout. The checkout may be too shallow "
            "or missing bundle prerequisites. stderr: " + result.stderr
        )
    return destination_ref


def _parse_ls_tree(raw: bytes) -> Iterable[tuple[bytes, bytes, bytes, bytes]]:
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ", 2)
        except ValueError as exc:
            raise GitProbeError(f"Unexpected git ls-tree record: {record!r}") from exc
        yield mode, object_type, object_id, path


def build_tree_manifest(
    repo: Path,
    ref: str,
    *,
    base_commit: str | None = None,
) -> dict:
    tree = _run_git(
        repo,
        ["ls-tree", "-r", "-z", "--full-tree", ref],
        text=False,
    ).stdout

    object_format = _run_git(
        repo,
        ["rev-parse", "--show-object-format"],
        text=True,
    ).stdout.strip()

    entries: list[dict] = []
    for mode_b, type_b, oid_b, path_b in _parse_ls_tree(tree):
        mode = mode_b.decode("ascii")
        object_type = type_b.decode("ascii")
        object_id = oid_b.decode("ascii")

        entry = {
            "path_b64": base64.b64encode(path_b).decode("ascii"),
            "mode": mode,
            "type": object_type,
        }

        if object_type == "blob":
            content = _run_git(repo, ["cat-file", "blob", object_id], text=False).stdout
            entry["content_sha256"] = hashlib.sha256(content).hexdigest()
            entry["size"] = len(content)
        elif object_type == "commit":
            # Gitlink/submodule. The referenced commit is part of the resulting tree identity.
            entry["gitlink_object_id"] = object_id
        else:
            entry["object_id"] = object_id

        entries.append(entry)

    entries.sort(key=lambda e: base64.b64decode(e["path_b64"]))

    manifest = {
        "schema": "agent-artifact-tree/v0-probe",
        "git_object_format": object_format,
        "base_commit": base_commit,
        "entries": entries,
    }
    return manifest


def canonical_manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def manifest_from_bundle(
    repo: Path,
    bundle_path: Path,
    *,
    base_commit: str | None = None,
) -> tuple[dict, str, str]:
    fetched_ref = fetch_bundle_to_ref(repo, bundle_path)
    try:
        manifest = build_tree_manifest(repo, fetched_ref, base_commit=base_commit)
        return manifest, manifest_digest(manifest), fetched_ref
    finally:
        _run_git(repo, ["update-ref", "-d", fetched_ref], check=False, text=True)


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--base-commit")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest, digest, _ = manifest_from_bundle(
        args.repo.resolve(),
        args.bundle.resolve(),
        base_commit=args.base_commit,
    )
    output = {
        "digest": digest,
        "manifest": manifest,
    }
    encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
