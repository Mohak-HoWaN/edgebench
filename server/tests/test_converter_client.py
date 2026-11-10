from __future__ import annotations

import sys
from pathlib import Path

from edgebench.config import Settings
from edgebench.converter_client import Converter


def converter(tmp_path: Path) -> Converter:
    return Converter(Settings(data_dir=tmp_path, converter_python=Path(sys.executable), _env_file=None))


def test_a_failing_log_callback_does_not_stop_the_converter_output_being_read(tmp_path: Path) -> None:
    """If nothing drains the pipe the child blocks on a full buffer and a timeout hides the cause. About 170 KB here."""
    code = "for i in range(3000): print('line', i, 'x' * 50)"

    def boom(line: str) -> None:
        raise RuntimeError("database is locked")

    outcome = converter(tmp_path)._run(["-c", code], timeout=30, on_line=boom)
    assert outcome.reason == "finished" and outcome.exit_code == 0
    assert "line 2999" in outcome.log


def test_a_hung_process_is_killed_at_the_timeout_and_the_end_of_its_output_is_kept(tmp_path: Path) -> None:
    code = "import time\nfor i in range(5000): print('row', i)\nprint('last words', flush=True)\ntime.sleep(60)"
    outcome = converter(tmp_path)._run(["-c", code], timeout=2)
    assert outcome.reason == "timeout" and outcome.exit_code != 0
    assert "last words" in outcome.log and len(outcome.log) <= 64 * 1024 + 100
