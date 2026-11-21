"""Offline controls for the manual final-status proof receipt.

    python .github/site/test_final_status_proof.py
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import final_status_proof as proof


def rust_log() -> str:
    return (f"running 1 test\ntest {proof.RUST_TEST} ... ok\n"
            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 40 filtered out\n")


def node_log() -> str:
    return "".join(f"ok {number} - {name}\n" for number, name in enumerate(proof.NODE_TESTS, 1)) + "# fail 0\n"


class ProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(proof.KIT.read_bytes())["cases"]

    def status_log(self, skipped=None) -> str:
        skipped = skipped or {}
        rows = [f"skipped  {case['name']}: {skipped[case['name']]}" if case["name"] in skipped
                else f"match    {case['name']}" for case in self.cases]
        judged = len(rows) - len(skipped)
        footer = {"cases": len(rows), "judged": judged, "skipped": len(skipped), "matched": judged, "all_matched": True}
        return "\n".join([*rows, json.dumps(footer)]) + "\n"

    def test_exact_unit_inventory_and_empty_or_skipped_controls(self):
        proof.rust_result(rust_log())
        proof.node_result(node_log())
        with self.assertRaisesRegex(proof.Unfinished, "one exact passing test"):
            proof.rust_result(rust_log().replace(proof.RUST_TEST, "status::tests::other"))
        with self.assertRaisesRegex(proof.Unfinished, "every named passing test"):
            proof.node_result(node_log().replace(proof.NODE_TESTS[0], proof.NODE_TESTS[0] + " # SKIP"))
        with self.assertRaisesRegex(proof.Unfinished, "every named passing test"):
            proof.node_result("# fail 0\n")

    def test_declared_windows_permissions_skip_is_named(self):
        case = next(case["name"] for case in self.cases if case.get("unreadable_mode"))
        reason = "this system cannot make a file or folder its own user cannot read"
        log = self.status_log({case: reason})
        result = proof.status_result(log, self.cases, "windows")
        self.assertEqual(result["skipped_cases"], [{"name": case, "reason": reason}])
        self.assertEqual((result["matched"], result["skipped"]), (252, 1))
        with self.assertRaisesRegex(proof.Unfinished, "port-skip"):
            proof.status_result(log, self.cases, "linux")
        with self.assertRaisesRegex(proof.Unfinished, "port-skip"):
            proof.status_result(self.status_log({self.cases[0]["name"]: reason}), self.cases, "windows")

    def test_exact_case_and_footer_inventory(self):
        log = self.status_log()
        self.assertEqual(proof.status_result(log, self.cases, "macos")["judged"], 253)
        with self.assertRaisesRegex(proof.Unfinished, "complete named case inventory"):
            proof.status_result("\n".join(log.splitlines()[1:]), self.cases, "linux")
        with self.assertRaisesRegex(proof.Unfinished, "port-skip"):
            proof.status_result(log.replace("match    ", "MISMATCH ", 1), self.cases, "linux")
        with self.assertRaisesRegex(proof.Unfinished, "incomplete or inconsistent"):
            proof.status_result(log.replace('"skipped": 0', '"skipped": false'), self.cases, "linux")
        with self.assertRaisesRegex(proof.Unfinished, "duplicate status footer"):
            proof.status_result(log.replace('"skipped": 0', '"skipped": 0, "skipped": 0'), self.cases, "linux")

    def test_even_a_passing_payload_cannot_override_native_error(self):
        def fail(command, *, stdout, **options):
            stdout.write(self.status_log().encode())
            self.assertEqual(options["timeout"], 3)
            return subprocess.CompletedProcess(command, 1)

        with patch.object(proof.subprocess, "run", side_effect=fail), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(proof.Unfinished, "native exit 1"):
                proof.run("status", ["test"], 3)
        timeout = subprocess.TimeoutExpired(["test"], 3)
        with patch.object(proof.subprocess, "run", side_effect=timeout), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(proof.Unfinished, "timed out"):
                proof.run("status", ["test"], 3)

    def test_wrong_lane_stops_before_any_checkout_or_test_command(self):
        with patch.dict(proof.os.environ, {}, clear=True), patch.object(proof, "run") as run:
            with self.assertRaisesRegex(proof.Unfinished, "wrong system or manual proof lane"):
                proof.invocation("linux")
            run.assert_not_called()

    def test_paired_commands_and_completed_receipt(self):
        log = self.status_log()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "kernel/target/release/dodona-kernel.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"fake executable")
            invocation = {"source": proof.SOURCE, "head": "a" * 40, "system": "windows", "run_id": 3, "attempt": 1}
            with (patch.object(proof, "ROOT", root), patch.object(proof, "invocation", return_value=invocation),
                    patch.object(proof, "run", side_effect=[rust_log(), node_log(), "", log, log]) as run):
                receipt = proof.prove("windows")
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["status_kit"]["rust"]["matched"], 253)
            self.assertEqual(receipt["status_kit"]["javascript"]["matched"], 253)
            self.assertEqual(run.call_count, 5)
            rust = "kernel/target/release/dodona-kernel.exe"
            node = ["node", "kernel2/dodona-kernel2.js"]
            self.assertEqual(run.call_args_list[0].args[1][-3:], [proof.RUST_TEST, "--", "--exact"])
            self.assertEqual(run.call_args_list[3].args[1][4:], ["--kernel", *node, "--", rust, "status"])
            self.assertEqual(run.call_args_list[4].args[1][4:], ["--kernel", rust, "--", *node, "status"])
            self.assertEqual([call.args[2] for call in run.call_args_list], [480, 60, 600, 360, 360])

    def test_second_status_is_observed_even_if_first_is_unfinished(self):
        log = self.status_log()
        with (patch.object(proof, "invocation", return_value={}),
                patch.object(proof, "run", side_effect=[rust_log(), node_log(), "", proof.Unfinished("rust status"), log]) as run):
            with self.assertRaisesRegex(proof.Unfinished, "rust status"):
                proof.prove("linux")
        self.assertEqual(run.call_count, 5)


if __name__ == "__main__":
    unittest.main()
