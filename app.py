#!/usr/bin/env python3
"""SELinux Manager — a PyQt6 desktop front-end for Linux."""
import argparse
from datetime import datetime
import sys

from PyQt6.QtCore import QProcess, QProcessEnvironment, QSignalBlocker, QTimer, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPushButton, QPlainTextEdit, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView, QAbstractItemView,
)

from backend import (Command, Demo, boolean_command, context_command,
                     launch_arguments, mode_command, module_command, parse_booleans,
                     parse_ports, parse_status, port_command, restore_command)


STYLE = """
QWidget { background: #101820; color: #e3edf5; font-size: 14px; }
QMainWindow { background: #101820; }
QLabel#title { font-size: 28px; font-weight: 700; }
QLabel#subtitle { color: #99afbf; }
QLabel#badge { background: #183c3c; color: #7be1be; border-radius: 6px; padding: 8px 12px; }
QLabel#notice { background: #253342; color: #c6dae8; padding: 12px; border-radius: 6px; }
QListWidget { background: #14212d; border: none; padding: 8px; }
QListWidget::item { padding: 15px 12px; border-radius: 6px; margin: 3px 0; }
QListWidget::item:selected { background: #224c52; color: #8ce8cf; }
QPushButton { background: #243746; border: 1px solid #385162; border-radius: 6px; padding: 9px 15px; }
QPushButton:hover { background: #304b5d; }
QPushButton:disabled { color: #637787; background: #1b2732; }
QPushButton#primary { background: #67d7b4; color: #102b24; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #93ebcf; }
QPushButton#primary:disabled { background: #294b44; color: #75998c; }
QLineEdit, QComboBox, QPlainTextEdit, QTableWidget {
 background: #15232f; border: 1px solid #314554; border-radius: 5px; padding: 7px; selection-background-color: #285b60;
}
QHeaderView::section { background: #223443; color: #b9cfde; border: none; padding: 10px; }
QTableWidget { gridline-color: #243543; }
QTableWidget::item { padding: 5px; }
QCheckBox { spacing: 8px; }
QStatusBar { background: #14212d; color: #afc4d2; }
QSplitter::handle { background: #304553; height: 3px; }
"""


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def note(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setObjectName("notice")
    return widget


def text_view():
    widget = QPlainTextEdit()
    widget.setReadOnly(True)
    widget.setFont(QFont("monospace", 11))
    return widget


def combo(values):
    widget = QComboBox()
    widget.addItems(values)
    return widget


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().hide()
    widget.setAlternatingRowColors(False)
    return widget


def fill_table(widget, rows):
    blocker = QSignalBlocker(widget)
    widget.setSortingEnabled(False)
    widget.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if value in ("on", "off"):
                item.setForeground(QColor("#7be1be" if value == "on" else "#a5b5c3"))
            widget.setItem(row, column, item)
    widget.setSortingEnabled(True)
    widget.setCurrentCell(-1, -1)
    del blocker


class Window(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.demo = Demo() if demo else None
        self.process = None
        self.busy = False
        self.active_command = None
        self.loaded = set()
        self.setWindowTitle("SELinux Manager" + (" · Demo" if demo else ""))
        self.resize(1120, 850)
        self.setMinimumSize(850, 680)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 12)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("SELinux Manager")
        title.setObjectName("title")
        titles.addWidget(title)
        subtitle = QLabel("Policy, permissions, and visibility in one place")
        subtitle.setObjectName("subtitle")
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch()
        self.badge = QLabel("DEMO · IN MEMORY" if demo else "LOCAL SYSTEM")
        self.badge.setObjectName("badge")
        header.addWidget(self.badge)
        layout.addLayout(header)
        if demo:
            layout.addWidget(note("Demo mode uses illustrative data. All changes stay in memory and disappear when you close the app."))
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter, 1)
        self.workspace = QWidget()
        body = QHBoxLayout(self.workspace)
        body.setContentsMargins(0, 12, 0, 0)
        self.navigation = QListWidget()
        self.navigation.addItems(["Overview", "Booleans", "Network ports", "File labeling", "Policy modules", "Audit denials"])
        self.navigation.setFixedWidth(185)
        body.addWidget(self.navigation)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        splitter.addWidget(self.workspace)
        self.make_overview()
        self.make_booleans()
        self.make_ports()
        self.make_contexts()
        self.make_modules()
        self.make_audit()
        log_box = QWidget()
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(0, 6, 0, 0)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Command activity"))
        log_header.addStretch()
        log_header.addWidget(button("Save log…", self.save_log))
        log_header.addWidget(button("Clear", lambda: self.log.clear()))
        log_layout.addLayout(log_header)
        self.log = text_view()
        self.log.document().setMaximumBlockCount(3000)
        log_layout.addWidget(self.log)
        splitter.addWidget(log_box)
        splitter.setSizes([580, 170])
        self.navigation.currentRowChanged.connect(self.select_page)
        self.navigation.setCurrentRow(0)
        self.statusBar().showMessage("Ready")
        QTimer.singleShot(0, lambda: self.refresh(0))

    def page(self, title, description):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 0, 0, 0)
        label = QLabel(title)
        label.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(label)
        layout.addWidget(note(description))
        self.pages.addWidget(page)
        return layout

    def make_overview(self):
        layout = self.page("System overview", "Inspect SELinux on this host. Runtime mode changes take effect immediately and do not change the boot configuration.")
        self.status_text = text_view()
        self.status_text.setPlaceholderText("Reading system status…")
        layout.addWidget(self.status_text, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Runtime mode"))
        self.mode = combo(["Enforcing", "Permissive"])
        row.addWidget(self.mode)
        self.mode_apply = button("Apply mode", self.change_mode, True)
        self.mode_apply.setEnabled(bool(self.demo))
        row.addWidget(self.mode_apply)
        row.addStretch()
        row.addWidget(button("Refresh status", lambda: self.refresh(0)))
        layout.addLayout(row)
        layout.addWidget(note("Enforcing blocks policy violations. Permissive logs them while allowing access. If SELinux is disabled, enabling it requires boot configuration and relabeling outside this app."))

    def make_booleans(self):
        layout = self.page("Policy booleans", "Toggle optional policy behavior. Select a boolean, choose its new state, and apply the change.")
        self.boolean_filter = QLineEdit()
        self.boolean_filter.setPlaceholderText("Filter booleans by name…")
        self.boolean_filter.textChanged.connect(lambda value: self.filter_table(self.booleans, value))
        layout.addWidget(self.boolean_filter)
        self.booleans = table(["Boolean", "Current state"])
        layout.addWidget(self.booleans, 1)
        row = QHBoxLayout()
        self.boolean_state = combo(["on", "off"])
        row.addWidget(QLabel("New state"))
        row.addWidget(self.boolean_state)
        self.persistent = QCheckBox("Persist across reboots")
        self.persistent.setChecked(True)
        row.addWidget(self.persistent)
        row.addStretch()
        row.addWidget(button("Refresh", lambda: self.refresh(1)))
        row.addWidget(button("Apply selected", self.change_boolean, True))
        layout.addLayout(row)
        self.booleans.itemSelectionChanged.connect(self.boolean_selected)

    def make_ports(self):
        layout = self.page("Network port mappings", "Assign a port or range to an SELinux type. Add creates a mapping; Modify overrides an existing mapping; Delete removes a local customization.")
        self.port_filter = QLineEdit()
        self.port_filter.setPlaceholderText("Filter by type, protocol, or port…")
        self.port_filter.textChanged.connect(lambda value: self.filter_table(self.ports_table, value))
        layout.addWidget(self.port_filter)
        self.ports_table = table(["SELinux type", "Protocol", "Ports"])
        layout.addWidget(self.ports_table, 1)
        form = QFormLayout()
        self.port_action = combo(["add", "modify", "delete"])
        self.protocol = combo(["tcp", "udp", "sctp", "dccp"])
        self.port_value = QLineEdit()
        self.port_value.setPlaceholderText("8080 or 8000-8010")
        self.port_type = QLineEdit()
        self.port_type.setPlaceholderText("http_port_t")
        form.addRow("Operation", self.port_action)
        form.addRow("Protocol", self.protocol)
        form.addRow("Port or range", self.port_value)
        form.addRow("SELinux type", self.port_type)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.local_ports = QCheckBox("Show local customizations only")
        self.local_ports.toggled.connect(lambda: self.refresh(2))
        row.addWidget(self.local_ports)
        row.addStretch()
        row.addWidget(button("Refresh", lambda: self.refresh(2)))
        row.addWidget(button("Apply mapping", self.change_port, True))
        layout.addLayout(row)
        self.port_action.currentTextChanged.connect(lambda v: self.port_type.setEnabled(v != "delete"))
        self.ports_table.itemSelectionChanged.connect(self.port_selected)

    def make_contexts(self):
        layout = self.page("File labeling", "Persistent rules match absolute paths or PCRE patterns. Saving a rule does not relabel files; use Preview or Restore labels afterward on a real filesystem path.")
        self.context_text = text_view()
        layout.addWidget(self.context_text, 1)
        form = QFormLayout()
        self.context_action = combo(["add", "modify", "delete"])
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("/srv/www(/.*)?")
        self.context_type = QLineEdit()
        self.context_type.setPlaceholderText("httpd_sys_content_t")
        self.file_type = QComboBox()
        for label, code in [("All files", "a"), ("Regular files", "f"), ("Directories", "d"),
                            ("Symbolic links", "l"), ("Sockets", "s"), ("Named pipes", "p"),
                            ("Character devices", "c"), ("Block devices", "b")]:
            self.file_type.addItem(label, code)
        form.addRow("Operation", self.context_action)
        form.addRow("Path pattern", self.pattern)
        form.addRow("File type", self.file_type)
        form.addRow("SELinux type", self.context_type)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.local_contexts = QCheckBox("Show local customizations only")
        self.local_contexts.setChecked(True)
        self.local_contexts.toggled.connect(lambda: self.refresh(3))
        row.addWidget(self.local_contexts)
        row.addStretch()
        row.addWidget(button("Refresh", lambda: self.refresh(3)))
        row.addWidget(button("Save rule", self.change_context, True))
        layout.addLayout(row)
        self.context_action.currentTextChanged.connect(lambda v: self.context_type.setEnabled(v != "delete"))
        self.restore_path = QLineEdit()
        self.restore_path.setPlaceholderText("Actual path to relabel, e.g. /srv/www")
        layout.addWidget(self.restore_path)
        row = QHBoxLayout()
        self.recursive = QCheckBox("Include subdirectories")
        row.addWidget(self.recursive)
        row.addStretch()
        row.addWidget(button("Preview labels", lambda: self.restore(True)))
        row.addWidget(button("Restore labels", lambda: self.restore(False), True))
        layout.addLayout(row)

    def make_modules(self):
        layout = self.page("Policy modules", "Inspect installed modules or install a trusted .pp / .cil policy file. Removing a module removes its policy rules at the default priority (400).")
        self.module_table = table(["Installed module"])
        layout.addWidget(self.module_table, 1)
        row = QHBoxLayout()
        row.addWidget(button("Refresh", lambda: self.refresh(4)))
        row.addStretch()
        row.addWidget(button("Remove selected", self.remove_module))
        row.addWidget(button("Install module…", self.install_module, True))
        layout.addLayout(row)

    def make_audit(self):
        layout = self.page("Audit denials", "Read recent AVC and USER_AVC events from the Linux audit log. Administrator access may be required. Events are displayed for investigation; no allow rules are generated.")
        row = QHBoxLayout()
        self.audit_period = combo(["today", "recent", "boot"])
        row.addWidget(QLabel("Since"))
        row.addWidget(self.audit_period)
        row.addStretch()
        row.addWidget(button("Read denials", lambda: self.refresh(5), True))
        layout.addLayout(row)
        self.audit_text = text_view()
        self.audit_text.setPlaceholderText("Click Read denials to query the audit log.")
        layout.addWidget(self.audit_text, 1)

    @staticmethod
    def filter_table(widget, query):
        for row in range(widget.rowCount()):
            values = " ".join(widget.item(row, col).text() for col in range(widget.columnCount()))
            widget.setRowHidden(row, query.lower() not in values.lower())

    def select_page(self, index):
        self.pages.setCurrentIndex(index)
        if index not in self.loaded and index not in (0, 5) and not self.busy:
            self.refresh(index)

    def refresh(self, index):
        if self.busy:
            return
        commands = {
            0: Command("sestatus"),
            1: Command("getsebool", ("-a",)),
            # These tools connect to the protected policy store even for listings.
            2: Command("semanage", ("port", "-l") + (("-C",) if self.local_ports.isChecked() else ()), True),
            3: Command("semanage", ("fcontext", "-l") + (("-C",) if self.local_contexts.isChecked() else ()), True),
            4: Command("semodule", ("-l",), True),
            5: Command("ausearch", ("--input-logs", "-m", "AVC,USER_AVC", "-ts", self.audit_period.currentText(), "-i"), True),
        }
        self.run(commands[index], lambda output: self.show_result(index, output))

    def show_result(self, index, output):
        self.loaded.add(index)
        if index == 0:
            self.status_text.setPlainText(output)
            status = {k.strip(): v.strip() for k, v in parse_status(output).items()}
            current = status.get("Current mode", "unknown").capitalize()
            self.mode_apply.setEnabled(current in ("Enforcing", "Permissive"))
            if current in ("Enforcing", "Permissive"):
                self.mode.setCurrentText(current)
            if not self.demo:
                self.badge.setText("SELINUX · " + (status.get("SELinux status", "unknown").upper() if current == "Unknown" else current.upper()))
        elif index == 1:
            fill_table(self.booleans, parse_booleans(output))
            self.filter_table(self.booleans, self.boolean_filter.text())
        elif index == 2:
            fill_table(self.ports_table, parse_ports(output))
            self.filter_table(self.ports_table, self.port_filter.text())
        elif index == 3:
            self.context_text.setPlainText(output or "No context rules found.")
        elif index == 4:
            fill_table(self.module_table, [[line] for line in output.splitlines() if line.strip()])
        else:
            self.audit_text.setPlainText(output or "No matching audit events.")

    def selected(self, widget):
        row = widget.currentRow()
        if row < 0 or widget.isRowHidden(row):
            raise ValueError("Select a visible row first.")
        return [widget.item(row, col).text() for col in range(widget.columnCount())]

    def boolean_selected(self):
        if self.booleans.currentRow() >= 0:
            self.boolean_state.setCurrentText(self.booleans.item(self.booleans.currentRow(), 1).text())

    def port_selected(self):
        if self.ports_table.currentRow() < 0:
            return
        row = self.ports_table.currentRow()
        kind, protocol, values = [self.ports_table.item(row, col).text() for col in range(3)]
        self.port_type.setText(kind)
        self.protocol.setCurrentText(protocol)
        self.port_value.setText(values if "," not in values else "")

    def apply(self, factory, explanation, refresh_index=None):
        if self.busy:
            return
        try:
            cmd = factory()
        except ValueError as error:
            QMessageBox.warning(self, "Check input", str(error))
            return
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Confirm SELinux change")
        message.setText(explanation)
        message.setInformativeText(("Demo mode: this affects sample data only.\n\n" if self.demo else "Administrator authentication may be requested.\n\n") + cmd.display)
        message.setStandardButtons(QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel)
        message.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if message.exec() != QMessageBox.StandardButton.Apply:
            return
        self.run(cmd, lambda _: self.refresh(refresh_index) if refresh_index is not None else None)

    def change_mode(self):
        self.apply(lambda: mode_command(self.mode.currentText()),
                   "Change runtime enforcement? Permissive mode allows policy violations; this change lasts until reboot.", 0)

    def change_boolean(self):
        self.apply(lambda: boolean_command(self.selected(self.booleans)[0], self.boolean_state.currentText() == "on", self.persistent.isChecked()),
                   "Update the selected policy boolean? Persisting the change updates the stored policy as well as the runtime value.", 1)

    def change_port(self):
        self.apply(lambda: port_command(self.port_action.currentText(), self.protocol.currentText(), self.port_value.text(), self.port_type.text()),
                   "Update this port mapping? The change persists across reboots. Delete removes a local customization and restores policy defaults.", 2)

    def change_context(self):
        self.apply(lambda: context_command(self.context_action.currentText(), self.pattern.text(), self.context_type.text(), self.file_type.currentData()),
                   "Update this persistent file context rule? Use a specific pattern. Existing labels change only after a separate restore operation.", 3)

    def restore(self, preview):
        factory = lambda: restore_command(self.restore_path.text(), self.recursive.isChecked(), preview)
        if preview:
            try:
                cmd = factory()
            except ValueError as error:
                QMessageBox.warning(self, "Check input", str(error))
                return
            self.run(cmd, lambda output: self.context_text.setPlainText(output or "No labels need changing."))
        else:
            self.apply(factory, "Restore labels to the policy defaults on this path? Custom labels may be replaced. Preview the operation first.")

    def install_module(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select trusted SELinux policy module", "", "Policy modules (*.pp *.cil);;All files (*)")
        if path:
            self.apply(lambda: module_command("install", path), "Install this trusted policy module? Its rules may grant additional access and persist across reboots.", 4)

    def remove_module(self):
        self.apply(lambda: module_command("remove", self.selected(self.module_table)[0].split()[0]),
                   "Remove this module at priority 400? Dependent services may lose access. A lower-priority module may become active.", 4)

    def append_log(self, text):
        self.log.appendPlainText(text.rstrip())

    def run(self, command, callback):
        if self.busy:
            return
        self.busy = True
        self.active_command = command
        self.workspace.setEnabled(False)
        self.statusBar().showMessage("Running: " + command.display)
        self.append_log(f"\n[{datetime.now():%H:%M:%S}] {'DEMO ' if self.demo else ''}$ {command.display}")
        if self.demo:
            QTimer.singleShot(180, lambda: self.demo_result(command, callback))
            return
        try:
            program, args = launch_arguments(command)
        except (ValueError, FileNotFoundError) as error:
            self.complete(False, "", str(error), callback)
            return
        process = QProcess(self)
        self.process = process
        process.setStandardInputFile(QProcess.nullDevice())
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("LC_ALL", "C")
        process.setProcessEnvironment(environment)
        self.stdout = bytearray()
        self.stderr = bytearray()
        process.readyReadStandardOutput.connect(lambda: self.collect(process, False))
        process.readyReadStandardError.connect(lambda: self.collect(process, True))
        process.errorOccurred.connect(lambda error: self.process_error(process, error, callback))
        process.finished.connect(lambda code, status: self.process_finished(process, code, status, command, callback))
        process.start(program, args)

    def demo_result(self, command, callback):
        try:
            output = self.demo.run(command)
        except Exception as error:
            self.complete(False, "", str(error), callback)
        else:
            self.complete(True, output, "", callback)

    def collect(self, process, stderr):
        data = bytes(process.readAllStandardError() if stderr else process.readAllStandardOutput())
        target = self.stderr if stderr else self.stdout
        # Drain the pipe even after reaching the display limit, so the child cannot block.
        if len(target) < 8_000_000:
            target.extend(data[:8_000_000 - len(target)])

    def process_error(self, process, error, callback):
        if process is self.process and error == QProcess.ProcessError.FailedToStart:
            self.process = None
            self.complete(False, "", process.errorString(), callback)
            process.deleteLater()

    def process_finished(self, process, code, status, command, callback):
        if process is not self.process:
            return
        self.collect(process, False)
        self.collect(process, True)
        output = self.stdout.decode("utf-8", "replace")
        error = self.stderr.decode("utf-8", "replace")
        normal = status == QProcess.ExitStatus.NormalExit
        no_matches = command.tool == "ausearch" and code == 1 and (output + error).strip() == "<no matches>"
        success = normal and (code == 0 or no_matches)
        if no_matches:
            output, error = "No matching audit events.\n", ""
        if not success:
            error = (error or output or process.errorString()) + f"\nExit code: {code}"
        if len(self.stdout) == 8_000_000 or len(self.stderr) == 8_000_000:
            self.append_log("Output limited to 8 MB per stream.")
        self.process = None
        process.deleteLater()
        self.complete(success, output, error, callback)

    def complete(self, success, output, error, callback):
        command = self.active_command
        self.busy = False
        self.workspace.setEnabled(True)
        self.active_command = None
        if output:
            self.append_log(output)
        if error:
            self.append_log(error)
        self.append_log("Completed successfully." if success else "Command failed.")
        self.statusBar().showMessage("Ready · last command succeeded" if success else "Last command failed · see activity log")
        if success:
            callback(output)
        else:
            explanation = ""
            if command and command.tool in ("semanage", "semodule") and any(
                marker in error.lower() for marker in (
                    "policy is not managed", "store cannot be accessed", "permission denied",
                    "could not connect to policy handler", "could not read from module store",
                )
            ):
                explanation = (
                    "The SELinux policy store could not be accessed. This command requested "
                    "administrator access automatically.\n\n"
                    "If authentication succeeded, check that this host has an installed, managed "
                    "SELinux policy matching the policy shown by sestatus, and that its store is "
                    "accessible to the administrator. If SELinux is disabled or no managed policy "
                    "is installed, policy-store management is unavailable.\n\n"
                    "Command details:\n"
                )
            QMessageBox.warning(self, "SELinux command failed", explanation + (error or "Unknown error")[:4000])

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save command activity", "selinux-manager.log", "Log files (*.log);;All files (*)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(self.log.toPlainText())
            except OSError as error:
                QMessageBox.warning(self, "Could not save log", str(error))

    def closeEvent(self, event):
        if self.busy:
            self.statusBar().showMessage("Wait for the current command to finish before closing.")
            event.ignore()
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Explore sample data without running system commands")
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("SELinux Manager")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(args.demo)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
