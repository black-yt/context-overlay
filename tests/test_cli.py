import subprocess
import sys


def test_cli_module_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "context_overlay.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "context-overlay" in result.stdout
    assert "serve" in result.stdout
