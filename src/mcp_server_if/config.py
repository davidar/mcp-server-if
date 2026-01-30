"""Configuration handling for mcp-server-if."""

import os
import shutil
from pathlib import Path


def get_games_dir() -> Path:
    """Get the games directory from environment or default."""
    env_dir = os.environ.get("IF_GAMES_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".mcp-server-if" / "games"


def get_bundled_glulxe() -> Path | None:
    """Get the bundled glulxe binary path if it exists."""
    package_dir = Path(__file__).parent
    for name in ("glulxe", "glulxe.exe"):
        bundled = package_dir / "bin" / name
        if bundled.exists() and bundled.is_file():
            return bundled
    return None


def get_glulxe_path() -> Path | None:
    """Get the glulxe binary path from environment, bundled, or auto-detect."""
    # 1. Check environment variable
    env_path = os.environ.get("IF_GLULXE_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists() and path.is_file():
            return path
        return None

    # 2. Check for bundled binary (installed with package)
    bundled = get_bundled_glulxe()
    if bundled:
        return bundled

    # 3. Try to find glulxe in PATH
    glulxe_in_path = shutil.which("glulxe")
    if glulxe_in_path:
        return Path(glulxe_in_path)

    # 4. Check common locations
    common_paths = [
        Path.home() / ".local" / "bin" / "glulxe",
        Path("/usr/local/bin/glulxe"),
        Path("/usr/bin/glulxe"),
    ]

    for path in common_paths:
        if path.exists() and path.is_file():
            return path

    return None


def _get_require_journal() -> bool:
    """Check if journal mode is enabled."""
    return os.environ.get("IF_REQUIRE_JOURNAL", "").lower() in ("1", "true", "yes")


class Config:
    """Server configuration."""

    def __init__(
        self,
        games_dir: Path | None = None,
        glulxe_path: Path | None = None,
        require_journal: bool | None = None,
    ):
        self.games_dir = games_dir or get_games_dir()
        self.glulxe_path: Path | None = glulxe_path or get_glulxe_path()
        self._require_journal = require_journal if require_journal is not None else _get_require_journal()

    @property
    def require_journal(self) -> bool:
        return self._require_journal

    def ensure_games_dir(self) -> None:
        """Ensure the games directory exists."""
        self.games_dir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        """Validate configuration. Returns list of errors."""
        errors = []
        if not self.glulxe_path:
            checked = [
                "IF_GLULXE_PATH env var",
                f"bundled binary at {Path(__file__).parent / 'bin'}",
                "glulxe in PATH",
            ]
            errors.append(
                "glulxe binary not found. Checked:\n"
                + "\n".join(f"  - {loc}" for loc in checked)
                + "\n\nFor development: run 'uv sync --reinstall-package mcp-server-if' to compile from source."
                + "\nFor production: install the wheel from PyPI."
            )
        elif not self.glulxe_path.exists():
            errors.append(f"glulxe binary not found at: {self.glulxe_path}")
        return errors
