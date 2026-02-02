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


def _get_bundled_binary(name: str) -> Path | None:
    """Get a bundled binary path if it exists."""
    package_dir = Path(__file__).parent
    for suffix in (name, f"{name}.exe"):
        bundled = package_dir / "bin" / suffix
        if bundled.exists() and bundled.is_file():
            return bundled
    return None


def _find_binary(name: str, env_var: str) -> Path | None:
    """Find a binary from env var, bundled, PATH, or common locations."""
    # 1. Check environment variable
    env_path = os.environ.get(env_var)
    if env_path:
        path = Path(env_path)
        if path.exists() and path.is_file():
            return path
        return None

    # 2. Check for bundled binary (installed with package)
    bundled = _get_bundled_binary(name)
    if bundled:
        return bundled

    # 3. Try to find in PATH
    in_path = shutil.which(name)
    if in_path:
        return Path(in_path)

    # 4. Check common locations
    common_paths = [
        Path.home() / ".local" / "bin" / name,
        Path("/usr/local/bin") / name,
        Path("/usr/bin") / name,
    ]

    for path in common_paths:
        if path.exists() and path.is_file():
            return path

    return None


# Keep public API for backwards compatibility
def get_bundled_glulxe() -> Path | None:
    """Get the bundled glulxe binary path if it exists."""
    return _get_bundled_binary("glulxe")


def get_glulxe_path() -> Path | None:
    """Get the glulxe binary path from environment, bundled, or auto-detect."""
    return _find_binary("glulxe", "IF_GLULXE_PATH")


def get_bundled_bocfel() -> Path | None:
    """Get the bundled bocfel binary path if it exists."""
    return _get_bundled_binary("bocfel")


def get_bocfel_path() -> Path | None:
    """Get the bocfel binary path from environment, bundled, or auto-detect."""
    return _find_binary("bocfel", "IF_BOCFEL_PATH")


def _get_require_journal() -> bool:
    """Check if journal mode is enabled."""
    return os.environ.get("IF_REQUIRE_JOURNAL", "").lower() in ("1", "true", "yes")


class Config:
    """Server configuration."""

    def __init__(
        self,
        games_dir: Path | None = None,
        glulxe_path: Path | None = None,
        bocfel_path: Path | None = None,
        require_journal: bool | None = None,
    ):
        self.games_dir = games_dir or get_games_dir()
        self.glulxe_path: Path | None = glulxe_path or get_glulxe_path()
        self.bocfel_path: Path | None = bocfel_path or get_bocfel_path()
        self._require_journal = require_journal if require_journal is not None else _get_require_journal()

    @property
    def require_journal(self) -> bool:
        return self._require_journal

    def ensure_games_dir(self) -> None:
        """Ensure the games directory exists."""
        self.games_dir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        """Validate glulxe configuration. Returns list of errors."""
        return self._validate_binary("glulxe", self.glulxe_path)

    def validate_bocfel(self) -> list[str]:
        """Validate bocfel configuration. Returns list of errors."""
        return self._validate_binary("bocfel", self.bocfel_path)

    def _validate_binary(self, name: str, path: Path | None) -> list[str]:
        errors = []
        if not path:
            checked = [
                f"IF_{name.upper()}_PATH env var",
                f"bundled binary at {Path(__file__).parent / 'bin'}",
                f"{name} in PATH",
            ]
            errors.append(
                f"{name} binary not found. Checked:\n"
                + "\n".join(f"  - {loc}" for loc in checked)
                + "\n\nFor development: run 'uv sync --reinstall-package mcp-server-if' to compile from source."
                + "\nFor production: install the wheel from PyPI."
            )
        elif not path.exists():
            errors.append(f"{name} binary not found at: {path}")
        return errors
