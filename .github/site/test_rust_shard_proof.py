import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import rust_shard_proof as proof

ROOT = Path(__file__).resolve().parents[2]
ENV = {"GITHUB_REPOSITORY": "sloik/dodona", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": proof.PROOF_REF,
       "GITHUB_WORKFLOW_REF": proof.WORKFLOW_REF, "GITHUB_WORKFLOW_SHA": "a" * 40, "GITHUB_SHA": "a" * 40,
       "GITHUB_JOB": proof.JOB, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
       "PROOF_ARTIFACT_ID": "456", "PROOF_ARTIFACT_DIGEST": "b" * 64}


def encoded(record):
    return (json.dumps(record) + "\n").encode("utf-8")


class RustShardProofTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "source"
        (self.source / "kernel").mkdir(parents=True)
        self.manifest = (self.source / "kernel" / "defects.json")
        self.manifest.write_bytes((ROOT / "kernel" / "defects.json").read_bytes())
        self.out = Path(directory.name) / "out"
        self.selected = [{"index": index, "name": defect["name"]}
                         for index, defect in enumerate(json.loads(self.manifest.read_bytes())["defects"], 1)
                         if index % 5 == 2]
        self.footer = {"defects": 55, "caught": 55, "unfinished": 0, "all_caught": False,
                       "shard": {"index": 2, "count": 5}, "inventory": {"sha256": proof.MANIFEST_SHA256, "count": 275},
                       "baseline_passed": True, "shard_passed": True, "covered": self.selected}
        self.enterContext(patch.dict(os.environ, ENV, clear=True))

    def capture(self, footer):
        with patch.object(proof, "git_output", side_effect=[proof.SOURCE, ""]), patch.object(proof, "judge", return_value=footer):
            proof.capture(self.source, self.out, 2, io.BytesIO())

    def test_exact_successful_footer_is_bound_to_the_attempt_and_upload(self):
        footer = encoded(self.footer)
        process = MagicMock()
        child = process.__enter__.return_value
        child.stdout = io.BytesIO(b"caught\n" + footer)
        child.wait.return_value = 0
        log = io.BytesIO()
        with patch.object(proof, "git_output", side_effect=[proof.SOURCE, ""]) as checkout, \
                patch.object(proof.subprocess, "Popen", return_value=process) as started:
            proof.capture(self.source, self.out, 2, log)
        checkout.assert_any_call(self.source, "status", "--porcelain", "--untracked-files=all")
        started.assert_called_once_with([sys.executable, "-u", "tools/kit_adequacy.py", "--shard", "2/5"],
                                        cwd=self.source, stdout=proof.subprocess.PIPE)
        self.assertEqual(log.getvalue(), b"caught\n" + footer)
        self.assertEqual({item.name for item in self.out.iterdir()}, {"binding.json", "receipt.json"})
        self.assertEqual((self.out / "receipt.json").read_bytes(), footer)
        marker = proof.bind(self.out, 2)
        self.assertEqual(marker, {"repository": "sloik/dodona", "workflow_ref": proof.WORKFLOW_REF, "workflow_sha": "a" * 40,
                                  "run_id": 123, "run_attempt": 2, "job": "rust-shard-fallback", "source_sha": proof.SOURCE,
                                  "manifest_sha256": proof.MANIFEST_SHA256, "footer_sha256": hashlib.sha256(footer).hexdigest(),
                                  "shard": {"index": 2, "count": 5}, "artifact_name": "issue41-rust-123-2-shard-2-of-5",
                                  "artifact_id": 456, "artifact_sha256": "b" * 64})

    def test_nonzero_exit_with_good_stdout_leaves_no_receipt(self):
        process = MagicMock()
        child = process.__enter__.return_value
        child.stdout = io.BytesIO(encoded(self.footer))
        child.wait.return_value = 1
        with patch.object(proof, "git_output", side_effect=[proof.SOURCE, ""]), \
                patch.object(proof.subprocess, "Popen", return_value=process), self.assertRaisesRegex(ValueError, "did not exit successfully"):
            proof.capture(self.source, self.out, 2, io.BytesIO())
        self.assertFalse(self.out.exists())

    def test_selector_counts_baseline_and_coverage_must_match(self):
        for change in ({"baseline_passed": False}, {"shard_passed": False}, {"all_caught": True}, {"unfinished": False},
                       {"shard": {"index": 1, "count": 1}}, {"shard": {"index": 3, "count": 5}},
                       {"covered": self.selected[:-1]}, {"inventory": {"sha256": "0" * 64, "count": 275}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.capture(encoded(dict(self.footer, **change)))
            self.assertFalse(self.out.exists())
        for raw in (encoded(self.footer).rstrip(b"\n"), encoded(self.footer).replace(b'"unfinished": 0', b'"unfinished": 4, "unfinished": 0')):
            with self.subTest(raw=raw[:120]), self.assertRaises(ValueError):
                self.capture(raw)
            self.assertFalse(self.out.exists())

    def test_wrong_source_inventory_or_lane_blocks_the_judge(self):
        for git_answers, event, wrong_manifest in ((["f" * 40], "workflow_dispatch", False),
                                                   ([proof.SOURCE, " M tools/kit_adequacy.py"], "workflow_dispatch", False),
                                                   ([], "pull_request", False),
                                                   ([proof.SOURCE, ""], "workflow_dispatch", True)):
            with self.subTest(event=event, git_answers=git_answers, wrong_manifest=wrong_manifest), \
                    patch.object(proof, "git_output", side_effect=git_answers), patch.object(proof, "judge") as judge, \
                    patch.dict(os.environ, {"GITHUB_EVENT_NAME": event}):
                if wrong_manifest:
                    self.manifest.write_bytes(self.manifest.read_bytes() + b"\n")
                with self.assertRaises(ValueError):
                    proof.capture(self.source, self.out, 2, io.BytesIO())
                judge.assert_not_called()
                self.assertFalse(self.out.exists())

    def test_publication_rejects_other_attempt_tampering_and_missing_upload_outputs(self):
        self.capture(encoded(self.footer))
        for key, other in (("GITHUB_RUN_ATTEMPT", "3"), ("PROOF_ARTIFACT_ID", ""), ("PROOF_ARTIFACT_DIGEST", "invalid")):
            with self.subTest(key=key), patch.dict(os.environ, {key: other}), self.assertRaises(ValueError):
                proof.bind(self.out, 2)
        with self.assertRaisesRegex(ValueError, "differs from this attempt"):
            proof.bind(self.out, 3)
        (self.out / "receipt.json").write_bytes(encoded(self.footer) + b"\n")
        with self.assertRaisesRegex(ValueError, "differs from this attempt"):
            proof.bind(self.out, 2)
