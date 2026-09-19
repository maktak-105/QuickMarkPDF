"""Verifies the dialog_guard fixture in conftest.py actually does its job:
an un-registered native dialog call must fail fast (raise), never block, and
a registered canned response must be returned without ever touching a real
dialog. This is the direct regression test for the "operation just sits
there because a file dialog popped up" failure described in
CPP_PORT_POSTMORTEM.md.
"""
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QDialog, QLineEdit

from conftest import UnexpectedDialog


def test_unregistered_open_file_dialog_raises_instead_of_blocking():
    with pytest.raises(UnexpectedDialog):
        QFileDialog.getOpenFileNames(None, "caption", "", "")


def test_unregistered_save_file_dialog_raises_instead_of_blocking():
    with pytest.raises(UnexpectedDialog):
        QFileDialog.getSaveFileName(None, "caption", "", "")


def test_unregistered_message_box_raises_instead_of_blocking():
    with pytest.raises(UnexpectedDialog):
        QMessageBox.warning(None, "title", "text")


def test_unregistered_input_dialog_raises_instead_of_blocking():
    with pytest.raises(UnexpectedDialog):
        QInputDialog.getText(None, "title", "label", QLineEdit.Password)


def test_registered_response_is_returned_without_raising(dialog_responses):
    dialog_responses.push("QFileDialog.getSaveFileName", ("C:/tmp/out.pdf", "PDF Files (*.pdf)"))
    result = QFileDialog.getSaveFileName(None, "caption", "", "")
    assert result == ("C:/tmp/out.pdf", "PDF Files (*.pdf)")


def test_queued_responses_are_consumed_in_order(dialog_responses):
    dialog_responses.push("QMessageBox.question", QMessageBox.Yes)
    dialog_responses.push("QMessageBox.question", QMessageBox.No)
    assert QMessageBox.question(None, "t", "q") == QMessageBox.Yes
    assert QMessageBox.question(None, "t", "q") == QMessageBox.No
    with pytest.raises(UnexpectedDialog):
        QMessageBox.question(None, "t", "q")  # queue exhausted


def test_allow_permits_unlimited_repeat_calls(dialog_responses):
    dialog_responses.allow("QMessageBox.information", QMessageBox.Ok)
    for _ in range(5):
        assert QMessageBox.information(None, "t", "m") == QMessageBox.Ok


def test_custom_qdialog_exec_is_guarded_by_class_name(qapp):
    class _Probe(QDialog):
        pass

    with pytest.raises(UnexpectedDialog):
        _Probe().exec()


def test_custom_qdialog_exec_callable_response_can_configure_instance(qapp, dialog_responses):
    class _Probe(QDialog):
        def __init__(self):
            super().__init__()
            self.configured = False

    def configure(dialog):
        dialog.configured = True
        return QDialog.DialogCode.Accepted

    dialog_responses.push("QDialog.exec:_Probe", configure)
    probe = _Probe()
    result = probe.exec()
    assert probe.configured is True
    assert result == QDialog.DialogCode.Accepted
