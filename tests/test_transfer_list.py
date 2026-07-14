from PyQt6.QtWidgets import QApplication

from ui.transfer_list import TransferList


def test_active_transfers_stay_above_recent_history(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = TransferList()
    received = tmp_path / "received.txt"
    received.write_text("ok", encoding="utf-8")

    try:
        finished = widget.add_transfer("finished", "finished.txt", 1024, False)
        widget.complete_transfer("finished", str(received))
        active = widget.add_transfer("active", "active.txt", 2048, True)
        app.processEvents()

        assert widget.list_layout.itemAt(0).widget() is active
        assert widget.list_layout.itemAt(1).widget() is finished
        assert widget.count_label.text() == "В процессе: 1 · Завершено: 1"
        assert widget.clear_btn.isVisibleTo(widget)
    finally:
        widget.deleteLater()
        app.processEvents()


def test_transfer_progress_and_clear_completed_history(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = TransferList()
    source = tmp_path / "source.bin"
    source.write_bytes(b"data")

    try:
        item = widget.add_transfer("transfer", "source.bin", 4096, True)
        widget.update_transfer("transfer", 2048, 1024 * 1024)

        assert item.percent_label.text() == "50%"
        assert item.size_label.text() == "2.0 KB / 4.0 KB"
        assert item.status_label.text() == "1.0 MB/s"

        widget.complete_transfer("transfer", str(source))
        assert item.status_label.text() == "Готово"
        assert item.open_btn.isVisibleTo(widget)

        widget.clear_completed()
        app.processEvents()
        assert not widget.transfers
        assert widget.empty_label.isVisibleTo(widget)
    finally:
        widget.deleteLater()
        app.processEvents()
