from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from git_tree_identity import manifest_from_bundle  # noqa: E402
from mutate_bundle import mutate_pending_bundle  # noqa: E402


def find_pending_bundle() -> Path:
    roots = [Path("/tmp/gh-aw"), Path.cwd()]
    found: list[Path] = []
    for root in roots:
        if root.exists():
            found.extend(path for path in root.rglob("*.bundle") if path.is_file())

    unique = sorted({path.resolve() for path in found})
    if len(unique) != 1:
        raise RuntimeError(
            "Expected exactly one platform-downloaded pending bundle, "
            f"found {len(unique)}: {unique}"
        )
    return unique[0]


def main() -> int:
    mutation = os.environ.get("PROBE_MUTATION", "none").strip().lower()
    if mutation not in {"none", "add", "remove", "rename", "chmod"}:
        raise RuntimeError(f"Unsupported PROBE_MUTATION={mutation!r}")

    repo = Path.cwd().resolve()
    bundle = find_pending_bundle()

    print(f"PLATFORM_OBSERVED_BUNDLE={bundle}")

    manifest_before, digest_before, _ = manifest_from_bundle(repo, bundle)
    print(f"IDENTITY_BEFORE={digest_before}")
    Path("/tmp/platform-observed-before.json").write_text(
        json.dumps(
            {"digest": digest_before, "manifest": manifest_before},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    if mutation == "none":
        print("PROBE_NO_SUBSTITUTION")
        return 0

    # Positive control: deliberately alter the exact bundle path that the
    # built-in Safe Outputs handler will consume later in this same job.
    mutate_pending_bundle(
        source_repo=repo,
        bundle_path=bundle,
        mutation=mutation,
    )

    manifest_after, digest_after, _ = manifest_from_bundle(repo, bundle)
    print(f"IDENTITY_AFTER={digest_after}")
    Path("/tmp/platform-observed-after.json").write_text(
        json.dumps(
            {"digest": digest_after, "manifest": manifest_after},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    if digest_before == digest_after:
        raise RuntimeError(
            "POSITIVE CONTROL FAILED: the selected mutation did not change "
            "the platform-observed complete-tree identity"
        )

    print(f"PROBE_OBSERVED_SUBSTITUTION mutation={mutation}")
    print(
        "Failing intentionally before the built-in Safe Outputs handler. "
        "No branch or pull request should be created."
    )
    return 42


if __name__ == "__main__":
    raise SystemExit(main())
