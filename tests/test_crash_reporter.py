import os
import subprocess
import sys
import textwrap
from pathlib import Path

from crash_reporter import install_qasync_timer_guard


def test_unhandled_qt_callback_is_logged_without_process_abort(tmp_path):
    log_path = tmp_path / "vlink-crash.log"
    script = textwrap.dedent(
        """
        import os
        from crash_reporter import install_exception_hooks

        install_exception_hooks(os.environ["VLINK_TEST_CRASH_LOG"])

        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication

        app = QApplication([])

        def fail():
            raise RuntimeError("VLINK_QT_CALLBACK_REGRESSION")

        QTimer.singleShot(0, fail)
        QTimer.singleShot(50, app.quit)
        app.exec()
        """
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["VLINK_TEST_CRASH_LOG"] = str(log_path)
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (src_path, env.get("PYTHONPATH", "")) if part
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    log = log_path.read_text(encoding="utf-8")
    assert "source=sys.excepthook" in log
    assert "VLINK_QT_CALLBACK_REGRESSION" in log


def test_qasync_guard_handles_stale_timer_event(tmp_path):
    log_path = tmp_path / "vlink-crash.log"
    assert install_qasync_timer_guard(log_path)

    import qasync

    timer = qasync._SimpleTimer()

    class StaleTimerEvent:
        @staticmethod
        def timerId():
            return 999_999

    timer.timerEvent(StaleTimerEvent())

    log = log_path.read_text(encoding="utf-8")
    assert "source=qasync._SimpleTimer.timerEvent" in log
    assert "KeyError" in log
