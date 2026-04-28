from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class _ConnectionTestWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    @Slot()
    def run(self) -> None:
        try:
            success, message = self._callback()
        except Exception as exc:
            success, message = False, str(exc)
        self.finished.emit(success, message)


class TestConnectionDialog(QDialog):
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle('测试连接')
        self.resize(420, 160)
        self.success: bool | None = None
        self.result_text = ''

        self._label = QLabel('正在测试连接...')
        self._label.setWordWrap(True)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._buttons.rejected.connect(self.reject)
        self._buttons.button(QDialogButtonBox.StandardButton.Close).setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._buttons)

        self._thread = QThread(self)
        self._worker = _ConnectionTestWorker(callback)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    @Slot(bool, str)
    def _on_finished(self, success: bool, message: str) -> None:
        self.success = success
        self.result_text = message
        self._label.setText(message)
        self._buttons.button(QDialogButtonBox.StandardButton.Close).setEnabled(True)

    def closeEvent(self, event) -> None:
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)
