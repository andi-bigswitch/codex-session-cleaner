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


def encrypted_reasoning(ciphertext: str = "encrypted-state") -> dict:
    return {
        "timestamp": "2026-06-27T00:00:01Z",
        "type": "response_item",
        "payload": {
            "type": "reasoning",
            "summary": [],
            "encrypted_content": ciphertext,
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
        self.backups = self.codex_home / "session-cleaner-backups"
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

    def run_cleaner(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), *args],
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def read_records(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text().splitlines()]

    def backup_paths(self) -> list[Path]:
        if not self.backups.exists():
            return []
        return sorted(path for path in self.backups.rglob("*.bak") if path.is_file())

    def test_cleans_top_level_and_compacted_reasoning(self) -> None:
        session_id = "11111111-1111-4111-8111-111111111111"
        compacted = {
            "timestamp": "2026-06-27T00:00:04Z",
            "type": "compacted",
            "payload": {
                "replacement_history": [
                    encrypted_reasoning("nested-fugu-state")["payload"],
                    encrypted_reasoning("wrapped-fugu-state"),
                    encrypted_reasoning("gAAAA-nested-state")["payload"],
                    visible_message("nested visible message")["payload"],
                ]
            },
        }
        mtime_ns = 1_780_000_000_123_456_789
        path = self.write_session(
            session_id,
            [
                session_meta(session_id),
                encrypted_reasoning("fugu-state"),
                encrypted_reasoning("gAAAA-openai-state"),
                visible_message(),
                compacted,
            ],
            mtime_ns,
        )

        result = self.run_cleaner(session_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Cleaned: removed 3 incompatible reasoning blocks.",
            result.stdout,
        )
        self.assertIn("Backup:", result.stdout)
        records = self.read_records(path)
        serialized = json.dumps(records)
        self.assertNotIn("fugu-state", serialized)
        self.assertIn("gAAAA-openai-state", serialized)
        self.assertIn("gAAAA-nested-state", serialized)
        self.assertIn("keep me", serialized)
        self.assertIn("nested visible message", serialized)
        self.assertEqual(records[0]["payload"]["id"], session_id)
        self.assertEqual(path.stat().st_mtime_ns, mtime_ns)
        self.assertEqual(list(self.sessions.glob("*.bak*")), [])
        backups = self.backup_paths()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].parent, self.backups / "2026" / "06" / "27")
        backup_text = backups[0].read_text()
        self.assertIn("fugu-state", backup_text)
        self.assertIn("gAAAA-openai-state", backup_text)
        self.assertEqual(backups[0].stat().st_mtime_ns, mtime_ns)

    def test_no_backup_skips_backup_for_changed_session(self) -> None:
        session_id = "66666666-6666-4666-8666-666666666666"
        path = self.write_session(
            session_id,
            [session_meta(session_id), encrypted_reasoning("fugu-state")],
            1_780_000_000_123_456_789,
        )

        result = self.run_cleaner("--no-backup", session_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Backup:", result.stdout)
        self.assertNotIn("fugu-state", path.read_text())
        self.assertEqual(self.backup_paths(), [])

    def test_already_compatible_session_does_not_create_backup(self) -> None:
        session_id = "77777777-7777-4777-8777-777777777777"
        self.write_session(
            session_id,
            [session_meta(session_id), encrypted_reasoning("gAAAA-openai-state")],
            1_780_000_000_123_456_789,
        )

        result = self.run_cleaner(session_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Already compatible: no incompatible reasoning blocks found.",
            result.stdout,
        )
        self.assertEqual(self.backup_paths(), [])

    def test_remove_all_encrypted_removes_compatible_prefixes(self) -> None:
        session_id = "55555555-5555-4555-8555-555555555555"
        compacted = {
            "timestamp": "2026-06-27T00:00:04Z",
            "type": "compacted",
            "payload": {
                "replacement_history": [
                    encrypted_reasoning("gAAAA-nested-state")["payload"],
                    visible_message("nested visible message")["payload"],
                ]
            },
        }
        path = self.write_session(
            session_id,
            [
                session_meta(session_id),
                encrypted_reasoning("gAAAA-openai-state"),
                visible_message(),
                compacted,
            ],
            1_780_000_000_123_456_789,
        )

        result = self.run_cleaner("--remove-all-encrypted", session_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Cleaned: removed 2 incompatible reasoning blocks.", result.stdout)
        serialized = json.dumps(self.read_records(path))
        self.assertNotIn("gAAAA", serialized)
        self.assertIn("keep me", serialized)
        self.assertIn("nested visible message", serialized)

    def test_last_selects_the_most_recent_session(self) -> None:
        old_id = "22222222-2222-4222-8222-222222222222"
        new_id = "33333333-3333-4333-8333-333333333333"
        old_path = self.write_session(
            old_id,
            [session_meta(old_id), encrypted_reasoning("old-fugu-state")],
            1_780_000_000_000_000_000,
        )
        new_path = self.write_session(
            new_id,
            [session_meta(new_id), encrypted_reasoning("new-fugu-state")],
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
            [session_meta(session_id), encrypted_reasoning()],
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
        self.assertEqual(self.backup_paths(), [])


if __name__ == "__main__":
    unittest.main()
