"""MCP server for playing Glulx interactive fiction games."""

from importlib.metadata import PackageNotFoundError, version

from .server import main

try:
    __version__ = version("mcp-server-if")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = ["__version__", "main"]
