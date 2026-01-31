"""Glulx game session management with RemGlk protocol."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

# Magic bytes for game formats
GLULX_MAGIC = b"Glul"  # Glulx game file
BLORB_MAGIC = b"FORM"  # Blorb container (FORM....IFRS)


def detect_game_format(content: bytes) -> str | None:
    """Detect game format from magic bytes. Returns 'ulx', 'gblorb', or None."""
    if content.startswith(GLULX_MAGIC):
        return "ulx"
    if content.startswith(BLORB_MAGIC) and len(content) > 12 and content[8:12] == b"IFRS":
        return "gblorb"
    return None


def find_game_file(game_dir: Path) -> Path | None:
    """Find the game file in a game directory (.ulx or .gblorb)."""
    for ext in ("ulx", "gblorb"):
        game_file = game_dir / f"game.{ext}"
        if game_file.exists():
            return game_file
    return None


class GlulxSession:
    """Manages a glulxe session with RemGlk JSON protocol."""

    def __init__(self, game_dir: Path, glulxe_path: Path | None = None):
        self.game_dir = game_dir
        self.glulxe_path = glulxe_path
        self.game_file = find_game_file(game_dir)
        self.state_dir = game_dir / "state"
        self.metadata_file = game_dir / "metadata.json"

    def has_state(self) -> bool:
        """Check if saved state exists."""
        return (self.state_dir / "autosave.json").exists()

    def load_metadata(self) -> dict:
        """Load session metadata."""
        if self.metadata_file.exists():
            try:
                return json.loads(self.metadata_file.read_text())
            except (OSError, json.JSONDecodeError):
                pass
        return {"gen": 0, "windows": [], "input_window": None, "input_type": "line"}

    def save_metadata(self, metadata: dict) -> None:
        """Save session metadata."""
        self.metadata_file.write_text(json.dumps(metadata, indent=2))

    def clear_state(self) -> None:
        """Clear saved game state."""
        if self.state_dir.exists():
            for f in self.state_dir.iterdir():
                f.unlink()
        if self.metadata_file.exists():
            self.metadata_file.unlink()

    async def run_turn(self, command: str | None = None) -> tuple[str, dict]:
        """
        Run a single turn of the game.

        Args:
            command: The command to send (None for initial turn)

        Returns:
            Tuple of (formatted output, updated metadata)
        """
        if not self.game_file or not self.game_file.exists():
            raise FileNotFoundError(f"Game file not found in: {self.game_dir}")

        if not self.glulxe_path or not self.glulxe_path.exists():
            raise FileNotFoundError(
                f"glulxe binary not found: {self.glulxe_path}\n"
                "Set IF_GLULXE_PATH or see README.md for build instructions."
            )

        # Ensure state directory exists
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Load metadata
        metadata = self.load_metadata()

        # Build glulxe command
        cmd = [
            str(self.glulxe_path),
            "-singleturn",
            "-fm",
            "--autosave",
            "--autodir",
            str(self.state_dir),
        ]

        if self.has_state():
            cmd.append("--autorestore")

        cmd.append(str(self.game_file))

        # Build input JSON
        if command is None or not self.has_state():
            # Initial turn
            input_json = {"type": "init", "gen": 0, "metrics": {"width": 80, "height": 24}, "support": []}
        else:
            # Subsequent turn
            input_type = metadata.get("input_type", "line")
            input_window = metadata.get("input_window")

            if input_window is None:
                raise ValueError("No input window available - game may have ended")

            if input_type == "char":
                # Character input - send single char or RemGlk special key name.
                # RemGlk special keys: return, escape, tab, left, right, up, down,
                # pageup, pagedown, home, end, func1-func12.
                # Regular chars (including space) are sent as literal single chars.
                if not command:
                    key = " "
                elif command in ("\n", "\r") or command.strip().lower() in ("enter", "return"):
                    key = "return"
                elif len(command) == 1:
                    key = command.lower()
                else:
                    key = command.strip().lower()
                input_json = {"type": "char", "gen": metadata["gen"], "window": input_window, "value": key}
            else:
                # Line input
                input_json = {"type": "line", "gen": metadata["gen"], "window": input_window, "value": command}

        # Run glulxe
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.game_dir,
        )

        input_bytes = (json.dumps(input_json) + "\n").encode()
        stdout, stderr = await proc.communicate(input_bytes)

        if proc.returncode != 0:
            error = stderr.decode("utf-8", errors="replace").strip()
            stdout_preview = stdout.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"glulxe failed (exit {proc.returncode}): {error}\nstdout: {stdout_preview}")

        # Parse output - RemGlk sends JSON terminated by blank line
        output_text = stdout.decode("utf-8", errors="replace")
        output_lines = output_text.strip().split("\n\n")

        if not output_lines:
            raise RuntimeError("No output from glulxe")

        # Parse the JSON output
        try:
            output = json.loads(output_lines[0])
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse glulxe output: {e}\nOutput: {output_text[:500]}") from e

        # Update metadata from output
        if "gen" in output:
            metadata["gen"] = output["gen"]

        # Update window list if present
        if "windows" in output:
            metadata["windows"] = output["windows"]

        # Update input expectations
        if output.get("input"):
            inp = output["input"][0]
            metadata["input_window"] = inp.get("id")
            metadata["input_type"] = inp.get("type", "line")
            metadata["input_gen"] = inp.get("gen", metadata["gen"])
        else:
            metadata["input_window"] = None
            metadata["input_type"] = None

        # Handle special input (file dialogs)
        if "specialinput" in output:
            special = output["specialinput"]
            if special.get("type") == "fileref_prompt":
                metadata["pending_fileref"] = True

        self.save_metadata(metadata)

        # Format output
        formatted = self._format_output(output, metadata.get("windows", []))

        return formatted, metadata

    def _format_output(self, output: dict, windows: list) -> str:
        """Format RemGlk output as readable text."""
        result = []

        # Build window type map
        window_types = {}
        for w in windows:
            window_types[w["id"]] = w.get("type", "buffer")

        # Process content
        content = output.get("content", [])
        grid_content = []
        buffer_content = []

        for item in content:
            win_id = item.get("id")
            win_type = window_types.get(win_id, "buffer")

            if win_type == "grid":
                # Status bar - extract lines
                for line in item.get("lines", []):
                    text = self._extract_text(line.get("content", []))
                    if text.strip():
                        grid_content.append(text)
            else:
                # Buffer window - extract text
                if item.get("clear"):
                    buffer_content = []  # Clear previous content

                for text_item in item.get("text", []):
                    if not text_item:
                        buffer_content.append("")
                    elif text_item.get("append"):
                        if buffer_content:
                            buffer_content[-1] += self._extract_text(text_item.get("content", []))
                        else:
                            buffer_content.append(self._extract_text(text_item.get("content", [])))
                    else:
                        buffer_content.append(self._extract_text(text_item.get("content", [])))

        # Format output
        if grid_content:
            result.append("=== " + " | ".join(grid_content) + " ===")
            result.append("")

        if buffer_content:
            result.extend(buffer_content)

        # Note if character input expected
        if output.get("input") and output["input"][0].get("type") == "char":
            result.append("")
            result.append("[Waiting for keypress]")

        return "\n".join(result)

    def _extract_text(self, content: list) -> str:
        """Extract text from RemGlk content array, preserving style info."""
        if not content:
            return ""

        result = []
        i = 0
        while i < len(content):
            item = content[i]
            if isinstance(item, dict):
                style = item.get("style", "normal")
                text = item.get("text", "")
                result.append(self._apply_style(style, text))
                i += 1
            elif isinstance(item, str):
                style = item
                if i + 1 < len(content) and isinstance(content[i + 1], str):
                    text = content[i + 1]
                    result.append(self._apply_style(style, text))
                    i += 2
                else:
                    i += 1
            else:
                i += 1

        return "".join(result)

    def _apply_style(self, style: str, text: str) -> str:
        """Apply markdown-style formatting based on Glulx style."""
        if not text:
            return ""

        if style in ("user1", "user2"):
            return f"[{text}]"
        elif style == "emphasized":
            return f"*{text}*"
        elif style in ("header", "subheader", "alert"):
            return f"**{text}**"
        elif style == "preformatted":
            return f"`{text}`"
        elif style == "note":
            return f"({text})"
        elif style == "blockquote":
            return f'"{text}"'
        elif style == "input":
            return f"> {text}"
        else:
            return text
