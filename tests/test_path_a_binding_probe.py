from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / ".github" / "probes"
sys.path.insert(0, str(PROBES))
SPEC = importlib.util.spec_from_file_location(
    "path_a_binding_probe", PROBES / "path_a_binding_probe.py"
)
assert SPEC and SPEC.loader
path_a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(path_a)


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


class PathABindingProbeTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path, str]:
        remote = root / "remote.git"
        remote.mkdir()
        run(["git", "init", "--bare"], remote)

        repo = root / "writer"
        repo.mkdir()
        run(["git", "init"], repo)
        run(["git", "config", "user.name", "Probe Tests"], repo)
        run(["git", "config", "user.email", "probe@example.invalid"], repo)
        (repo / "probe-target.txt").write_text("base\n", encoding="utf-8")
        run(["git", "add", "."], repo)
        run(["git", "commit", "-m", "base"], repo)
        base = run(["git", "rev-parse", "HEAD"], repo)

        run(["git", "switch", "-c", "proposed"], repo)
        (repo / "probe-target.txt").write_text(
            "base\nproposed\n", encoding="utf-8"
        )
        run(["git", "add", "probe-target.txt"], repo)
        run(["git", "commit", "-m", "proposed"], repo)
        bundle = root / "attested.bundle"
        run(["git", "bundle", "create", str(bundle), "proposed"], repo)
        return repo, bundle, remote, base

    def invoke(self, root: Path, mode: str) -> tuple[int, str, bool]:
        repo, bundle, remote, base = self.make_fixture(root)
        output = io.StringIO()
        with redirect_stdout(output):
            status = path_a.run_probe(
                repo=repo,
                bundle=bundle,
                remote_url=str(remote),
                remote_branch=f"probe-{mode}",
                base_commit=base,
                mode=mode,
            )
        mutation_exists = (repo / "path-a-readback-divergence.txt").exists()
        return status, output.getvalue(), mutation_exists

    def test_clean_requires_all_three_identities_to_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, output, _ = self.invoke(Path(tmp), path_a.CLEAN)

        self.assertEqual(0, status)
        identities = dict(
            line.split("=", 1)
            for line in output.splitlines()
            if line.startswith(
                ("ATTESTED_IDENTITY=", "PREWRITE_IDENTITY=", "REMOTE_IDENTITY=")
            )
        )
        self.assertEqual(3, len(identities))
        self.assertEqual(1, len(set(identities.values())))
        self.assertIn("BINDING_PROBE_RESULT=CLEAN_MATCH", output)

    def test_readback_divergence_reports_only_expected_remote_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, output, mutation_exists = self.invoke(
                Path(tmp), path_a.READBACK_DIVERGENCE
            )

        self.assertEqual(42, status)
        self.assertIn(
            "BINDING_FAILURE_REASON=REMOTE_IDENTITY_MISMATCH_EXPECTED", output
        )
        values = [
            line.split("=", 1)[1]
            for line in output.splitlines()
            if line.startswith(
                ("ATTESTED_IDENTITY=", "PREWRITE_IDENTITY=", "REMOTE_IDENTITY=")
            )
        ]
        self.assertEqual(values[0], values[1])
        self.assertNotEqual(values[0], values[2])
        self.assertTrue(mutation_exists)

    def test_push_failure_is_operational_not_expected_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, bundle, _, base = self.make_fixture(root)
            output = io.StringIO()
            with redirect_stdout(output):
                with self.assertRaisesRegex(
                    path_a.BindingProbeError, "PUSH_OR_AUTHENTICATION_FAILURE"
                ):
                    path_a.run_probe(
                        repo=repo,
                        bundle=bundle,
                        remote_url=str(root / "missing.git"),
                        remote_branch="probe-failure",
                        base_commit=base,
                        mode=path_a.READBACK_DIVERGENCE,
                    )

        self.assertNotIn("BINDING_FAILURE_REASON=", output.getvalue())


if __name__ == "__main__":
    unittest.main()
