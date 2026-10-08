import subprocess
import sys
from pathlib import Path

from briefing.cli import main

ROOT = Path(__file__).resolve().parent.parent


def test_schedule_command_runs(capsys):
    assert main(["schedule"]) == 0
    out = capsys.readouterr().out
    assert "05:50 Europe/Rome" in out and "1 research desk\n" in out and "5 research desks" in out


def test_module_entry_point_starts():
    """`python -m briefing` is what the workflow runs: it must import cleanly."""
    proc = subprocess.run([sys.executable, "-m", "briefing", "run", "--help"], cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "--force" in proc.stdout
