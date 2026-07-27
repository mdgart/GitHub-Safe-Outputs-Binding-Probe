from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from git_tree_identity import GitProbeError, resolve_bundle_head


def run(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise GitProbeError(
            f"{' '.join(args)} failed with {result.returncode}: {result.stderr}"
        )
    return result.stdout.strip()


def mutate_pending_bundle(
    *,
    source_repo: Path,
    bundle_path: Path,
    mutation: str,
) -> None:
    _, source_ref = resolve_bundle_head(bundle_path)

    with tempfile.TemporaryDirectory(prefix="binding-probe-") as tmp:
        work = Path(tmp) / "repo"
        run(["git", "clone", "--no-checkout", str(source_repo), str(work)], cwd=source_repo)
        temp_ref = "refs/heads/probe-pending"
        run(
            ["git", "fetch", str(bundle_path), f"{source_ref}:{temp_ref}"],
            cwd=work,
        )
        run(["git", "checkout", "probe-pending"], cwd=work)
        run(["git", "config", "user.name", "Binding Probe"], cwd=work)
        run(["git", "config", "user.email", "binding-probe@example.invalid"], cwd=work)

        if mutation == "add":
            (work / "backdoor.py").write_text(
                "print('substituted artifact')\n", encoding="utf-8"
            )
            run(["git", "add", "backdoor.py"], cwd=work)

        elif mutation == "remove":
            target = work / "remove-me.txt"
            if not target.exists():
                raise GitProbeError("remove-me.txt does not exist in pending tree")
            target.unlink()
            run(["git", "add", "-A", "remove-me.txt"], cwd=work)

        elif mutation == "rename":
            source = work / "rename-me.txt"
            if not source.exists():
                raise GitProbeError("rename-me.txt does not exist in pending tree")
            run(["git", "mv", "rename-me.txt", "renamed-by-attacker.txt"], cwd=work)

        elif mutation == "chmod":
            target = work / "script.sh"
            if not target.exists():
                raise GitProbeError("script.sh does not exist in pending tree")
            current_mode = target.stat().st_mode
            target.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            run(["git", "add", "script.sh"], cwd=work)

        else:
            raise ValueError(f"Unknown mutation: {mutation}")

        run(["git", "commit", "-m", f"probe substitution: {mutation}"], cwd=work)

        recreated = Path(tmp) / "substituted.bundle"
        # Preserve exactly one branch head. The Safe Outputs handler can consume
        # this from the same on-disk path it was already going to use.
        run(["git", "bundle", "create", str(recreated), "probe-pending"], cwd=work)
        shutil.copyfile(recreated, bundle_path)


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--mutation",
        required=True,
        choices=["add", "remove", "rename", "chmod"],
    )
    args = parser.parse_args()
    mutate_pending_bundle(
        source_repo=args.repo.resolve(),
        bundle_path=args.bundle.resolve(),
        mutation=args.mutation,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
