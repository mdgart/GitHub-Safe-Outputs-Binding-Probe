from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from probe.git_tree_identity import manifest_from_bundle
from probe.mutate_bundle import mutate_pending_bundle


def run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed with {result.returncode}: {result.stderr}"
        )
    return result.stdout.strip()


class TreeIdentityMutationTests(unittest.TestCase):
    def make_fixture(self, directory: Path) -> tuple[Path, Path]:
        repo = directory / "repo"
        repo.mkdir()
        run(["git", "init"], repo)
        run(["git", "config", "user.name", "Probe Tests"], repo)
        run(["git", "config", "user.email", "probe@example.invalid"], repo)

        (repo / "probe-target.txt").write_text("base\n", encoding="utf-8")
        (repo / "remove-me.txt").write_text("remove me\n", encoding="utf-8")
        (repo / "rename-me.txt").write_text("rename me\n", encoding="utf-8")
        (repo / "script.sh").write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
        (repo / "script.sh").chmod(0o644)

        run(["git", "add", "."], repo)
        run(["git", "commit", "-m", "base"], repo)
        run(["git", "branch", "-M", "main"], repo)

        run(["git", "checkout", "-b", "agent-change"], repo)
        (repo / "probe-target.txt").write_text("base\nagent change\n", encoding="utf-8")
        run(["git", "add", "probe-target.txt"], repo)
        run(["git", "commit", "-m", "agent change"], repo)

        bundle = directory / "agent.bundle"
        run(["git", "bundle", "create", str(bundle), "agent-change"], repo)
        return repo, bundle

    def assert_mutation_changes_identity(self, mutation: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, bundle = self.make_fixture(root)

            _, before, _ = manifest_from_bundle(repo, bundle)
            mutate_pending_bundle(
                source_repo=repo,
                bundle_path=bundle,
                mutation=mutation,
            )
            _, after, _ = manifest_from_bundle(repo, bundle)

            self.assertNotEqual(before, after, mutation)

    def test_added_file_changes_identity(self):
        self.assert_mutation_changes_identity("add")

    def test_removed_file_changes_identity(self):
        self.assert_mutation_changes_identity("remove")

    def test_renamed_file_changes_identity(self):
        self.assert_mutation_changes_identity("rename")

    def test_mode_change_changes_identity(self):
        self.assert_mutation_changes_identity("chmod")


if __name__ == "__main__":
    unittest.main()
