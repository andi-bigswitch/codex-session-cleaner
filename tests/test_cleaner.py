from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "codex-session-cleaner"


def session_meta(session_id: str) -> dict:
    return {
        "timestamp": "2026-06-27T00:00:00Z",
        "type": "session_meta",
        "payload": {"id": session_id, "model_provider": "sakana"},
    }


def incompatible_reasoning(ciphertext: str = "fugu-encrypted-state") -> dict:
    return {
        "timestamp": "2026-06-27T00:00:01Z",
        "type": "response_item",
        "payload": {
            "type": "reasoning",
            "summary": [],
            "encrypted_content": ciphertext,
        },
    }


def compatible_reasoning() -> dict:
    return {
        "timestamp": "2026-06-27T00:00:02Z",
        "type": "response_item",
        "payload": {
            "type": "reasoning",
            "summary": [],
            "encrypted_content": "gAAAA-openai-state",
        },
    }


def visible_message(text: str = "keep me") -> dict:
    return {
        "timestamp": "2026-06-27T00:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        },
    }


class CleanerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.codex_home = Path(self.temp_dir.name)
        self.sessions = self.codex_home / "sessions" / "2026" / "06" / "27"
        self.sessions.mkdir(parents=True)
        self.env = os.environ.copy()
        self.env["CODEX_HOME"] = str(self.codex_home)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_session(
        self, session_id: str, records: list[dict], mtime_ns: int
    ) -> Path:
        path = self.sessions / f"rollout-test-{session_id}.jsonl"
        with path.open("w", encoding="utf-8") as target:
            for record in records:
                target.write(json.dumps(record, separators=(",", ":")) + "\n")
        os.utime(path, ns=(mtime_ns, mtime_ns))
        return path

    def run_cleaner(self, selector: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), selector],
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def read_records(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_cleans_top_level_and_compacted_reasoning(self) -> None:
        session_id = "11111111-1111-4111-8111-111111111111"
        compacted = {
            "timestamp": "2026-06-27T00:00:04Z",
            "type": "compacted",
            "payload": {
                "replacement_history": [
                    incompatible_reasoning("nested-fugu-state")["payload"],
                    incompatible_reasoning("wrapped-fugu-state"),
                    compatible_reasoning()["payload"],
                    visible_message("nested visible message")["payload"],
                ]
            },
        }
        mtime_ns = 1_780_000_000_123_456_789
        path = self.write_session(
            session_id,
            [
                session_meta(session_id),
                incompatible_reasoning(),
                compatible_reasoning(),
                visible_message(),
                compacted,
            ],
            mtime_ns,
        )

        result = self.run_cleaner(session_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Cleaned: removed 3 incompatible reasoning blocks.", result.stdout)
        records = self.read_records(path)
        serialized = json.dumps(records)
        self.assertNotIn("fugu-state", serialized)
        self.assertIn("gAAAA-openai-state", serialized)
        self.assertIn("keep me", serialized)
        self.assertIn("nested visible message", serialized)
        self.assertEqual(records[0]["payload"]["id"], session_id)
        self.assertEqual(path.stat().st_mtime_ns, mtime_ns)
        self.assertEqual(list(self.sessions.glob("*.bak*")), [])

    def test_last_selects_the_most_recent_session(self) -> None:
        old_id = "22222222-2222-4222-8222-222222222222"
        new_id = "33333333-3333-4333-8333-333333333333"
        old_path = self.write_session(
            old_id,
            [session_meta(old_id), incompatible_reasoning("old-fugu-state")],
            1_780_000_000_000_000_000,
        )
        new_path = self.write_session(
            new_id,
            [session_meta(new_id), incompatible_reasoning("new-fugu-state")],
            1_780_000_001_000_000_000,
        )

        result = self.run_cleaner("last")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Session ID: {new_id}", result.stdout)
        self.assertIn("old-fugu-state", old_path.read_text())
        self.assertNotIn("new-fugu-state", new_path.read_text())

    def test_invalid_json_does_not_modify_the_session(self) -> None:
        session_id = "44444444-4444-4444-8444-444444444444"
        path = self.write_session(
            session_id,
            [session_meta(session_id), incompatible_reasoning()],
            1_780_000_000_000_000_000,
        )
        with path.open("a", encoding="utf-8") as target:
            target.write("{broken json\n")
        original = path.read_bytes()

        result = self.run_cleaner(session_id)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid JSONL", result.stderr)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.sessions.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
