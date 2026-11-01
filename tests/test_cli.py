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


def test_no_evening_edition_friday_to_sunday(capsys):
    from datetime import datetime

    from briefing.dispatch import TIMEZONE, Edition, is_day_off

    rome = lambda d, h, m: datetime(2026, 10, d, h, m, tzinfo=TIMEZONE)  # Oct 2026: 30 = Friday
    assert not is_day_off(Edition.EVENING, rome(29, 20, 50))   # Thursday evening
    assert is_day_off(Edition.EVENING, rome(30, 20, 50))       # Friday evening
    assert is_day_off(Edition.EVENING, rome(31, 0, 30))        # late backup of Friday's slot
    assert is_day_off(Edition.EVENING, rome(31, 20, 50))       # Saturday
    assert is_day_off(Edition.EVENING, rome(25, 20, 50))       # Sunday
    assert not is_day_off(Edition.EVENING, rome(26, 20, 50))   # Monday
    assert not is_day_off(Edition.DAILY, rome(30, 5, 50))      # mornings always run
    assert main(["run", "PM", "--now", "2026-10-30T19:50:00Z", "--no-send"]) == 0
    assert "no edition on this day" in capsys.readouterr().out
