# codex-session-cleaner

`codex-session-cleaner` is a small recovery tool for continuing a local Codex
CLI session after switching from a provider such as Sakana Fugu to an OpenAI
GPT model.

Codex persists provider-specific encrypted reasoning in its JSONL session
history. A different provider cannot decrypt that hidden state, so replaying
the same session can fail with `invalid_encrypted_content`. This tool removes
the incompatible encrypted reasoning records while preserving the visible
conversation, tool records, session ID, file name, permissions, and timestamp.

This is an unofficial workaround for
[openai/codex#17541](https://github.com/openai/codex/issues/17541).

## When it is useful

The tool has been useful for moving an ongoing task between Sakana Fugu and
regular OpenAI GPT sessions when one provider reaches a rate limit. Run the
cleaner after closing the Fugu-backed session and before resuming that session
with GPT.

The cleaner does not decrypt or translate reasoning. It deliberately discards
only hidden, provider-specific reasoning state. The visible conversation and
normal Codex records remain in place.

## Requirements

- Python 3.10 or newer
- Codex CLI sessions stored under `${CODEX_HOME:-~/.codex}/sessions`
- Linux or macOS

There are no third-party Python dependencies.

## Install

```bash
git clone https://github.com/safrano9999/codex-session-cleaner.git
install -m 755 codex-session-cleaner/codex-session-cleaner ~/.local/bin/
```

Make sure `~/.local/bin` is on your `PATH`.

## Usage

First, stop any Codex process that is using the session. Then clean either a
specific session:

```bash
codex-session-cleaner 019dc8d9-3ff9-7f23-bb45-54818d3b3d9c
```

or the most recently modified session:

```bash
codex-session-cleaner last
```

You can then resume the same session ID with your intended OpenAI GPT profile.

## Safety and limitations

- Back up the affected JSONL file before running the tool. The cleaner does
  not create backups.
- Do not run it while Codex is writing to the session. It detects concurrent
  changes and aborts, but closing the session first is still required.
- Every JSONL record is validated before the original file is replaced.
- Replacement is atomic and the original file mode and timestamps are kept.
- The current compatibility rule keeps encrypted reasoning whose ciphertext
  starts with `gAAA` and removes other encrypted reasoning records. This is a
  targeted Sakana-Fugu-to-OpenAI workaround, not a universal repair strategy.
- It will not fix account or organization-key mismatches when both providers'
  ciphertext uses the same prefix.
- Removing hidden reasoning can reduce model context even though visible
  messages and tool history are preserved.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
