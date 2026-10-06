"""Offscreen integration checks; never invoke SELinux system tools."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
import time
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtCore import QSettings, Qt
    from app import Window, STYLE
    from themes import COLORS, ThemeController
    from backend import Command, boolean_command
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setStyle("Fusion")
        cls.qt.setStyleSheet(STYLE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.theme = ThemeController(self.qt, settings=settings, connect_platform=False)
        self.window = Window(demo=True, theme=self.theme)
        self.window.show()
        self.wait_idle()

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.qt.processEvents()
        self.theme.deleteLater()
        self.qt.processEvents()
        self.temp.cleanup()

    def wait_idle(self):
        deadline = time.monotonic() + 5
        self.qt.processEvents()
        while self.window.busy and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(0.005)
        self.assertFalse(self.window.busy, "Job did not finish")
        self.qt.processEvents()

    def test_all_pages_and_search(self):
        for page in range(7):
            self.window.navigation.setCurrentRow(page)
            self.wait_idle()
            self.assertEqual(self.window.pages.currentIndex(), page)
        self.window.refresh(5)
        self.wait_idle()
        self.assertIn("denied", self.window.audit_text.toPlainText())
        self.window.boolean_filter.setText("httpd")
        visible = [self.window.booleans.item(r, 0).text() for r in range(self.window.booleans.rowCount())
                   if not self.window.booleans.isRowHidden(r)]
        self.assertEqual(len(visible), 2)

    def test_settings_switch_themes_and_remember_choice(self):
        self.window.navigation.setCurrentRow(6)
        for choice in ("dark", "light"):
            self.window.theme_buttons[choice].click()
            self.qt.processEvents()
            self.assertEqual(self.theme.effective, choice)
            self.assertEqual(self.theme.settings.value("appearance/theme"), choice)
            self.assertIn(COLORS[choice]["bg"], self.qt.styleSheet())
        restored = ThemeController(self.qt, self.theme.settings, connect_platform=False)
        self.assertEqual(restored.preference, "light")
        restored.deleteLater()

    def test_small_window_scrolls_without_overlapping_form_fields(self):
        self.window.resize(940, 800)
        self.window.navigation.setCurrentRow(3)
        self.wait_idle()
        fields = [self.window.context_action, self.window.pattern, self.window.file_type, self.window.context_type]
        for previous, following in zip(fields, fields[1:]):
            self.assertGreaterEqual(previous.height(), 38)
            self.assertFalse(previous.geometry().intersects(following.geometry()))
        scroll = self.window.pages.currentWidget()
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)

    def test_live_system_theme_changes_and_manual_override(self):
        self.theme.set_preference("system")
        self.theme.system_changed(Qt.ColorScheme.Dark)
        self.assertEqual(self.theme.effective, "dark")
        self.theme.system_changed(Qt.ColorScheme.Light)
        self.assertEqual(self.theme.effective, "light")
        self.theme.set_preference("dark")
        self.theme.system_changed(Qt.ColorScheme.Light)
        self.assertEqual(self.theme.effective, "dark")
        self.theme.set_preference("system")
        self.assertEqual(self.theme.effective, "light")

    def test_portal_preference_and_boolean_contrast(self):
        self.window.navigation.setCurrentRow(1)
        self.wait_idle()
        self.theme.set_preference("system")
        self.theme.system_changed(Qt.ColorScheme.Unknown)
        for value, effective in ((1, "dark"), (2, "light")):
            self.theme.update_portal(value)
            self.assertEqual(self.theme.effective, effective)
            for row in range(self.window.booleans.rowCount()):
                item = self.window.booleans.item(row, 1)
                expected = COLORS[effective]["success" if item.text() == "on" else "muted"]
                self.assertEqual(item.foreground().color().name(), expected)
        self.theme.update_portal(0)
        self.assertEqual(self.theme.effective, self.theme.fallback)

    def test_portal_startup_read_and_typed_notifications(self):
        from PyQt6.QtDBus import QDBusMessage, QDBusPendingCall, QDBusVariant
        from unittest.mock import Mock
        request = QDBusMessage.createMethodCall("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Settings", "Read")
        reply = request.createReply([QDBusVariant(QDBusVariant(1))])
        bus = Mock()
        bus.isConnected.return_value = True
        bus.asyncCall.return_value = QDBusPendingCall.fromCompletedCall(reply)
        with patch("themes.QDBusConnection.sessionBus", return_value=bus):
            theme = ThemeController(self.qt, self.theme.settings)
            # Finished replies are delivered through the Qt event loop.
            for _ in range(10):
                self.qt.processEvents()
            self.assertEqual(theme.portal_scheme, "dark")
            self.assertEqual(theme.effective, "dark")
            registered_slot = bus.connect.call_args.args[-1]
            registered_slot("org.freedesktop.appearance", "color-scheme", QDBusVariant(2))
            self.assertEqual(theme.effective, "light")
            registered_slot("unrelated", "color-scheme", QDBusVariant(1))
            self.assertEqual(theme.effective, "light")
            theme.set_preference("dark")
            registered_slot("org.freedesktop.appearance", "color-scheme", QDBusVariant(2))
            self.assertEqual(theme.effective, "dark")
            theme.set_preference("system")
            self.assertEqual(theme.effective, "light")
            theme.deleteLater()

    def test_missing_portal_is_a_nonfatal_fallback(self):
        from unittest.mock import Mock
        bus = Mock()
        bus.isConnected.return_value = False
        with patch("themes.QDBusConnection.sessionBus", return_value=bus):
            theme = ThemeController(self.qt, self.theme.settings)
            self.assertIn(theme.effective, ("light", "dark"))
            bus.asyncCall.assert_not_called()
            theme.deleteLater()

    def test_policy_store_reads_always_request_elevation(self):
        for index in range(6):
            with self.subTest(page=index), patch.object(self.window, "run") as run:
                self.window.refresh(index)
                command = run.call_args.args[0]
                self.assertEqual(command.privileged, index in (2, 3, 4, 5))
                self.assertFalse(command.mutation)
        self.window.local_ports.setChecked(True)
        self.wait_idle()
        with patch.object(self.window, "run") as run:
            self.window.refresh(2)
            command = run.call_args.args[0]
            self.assertTrue(command.privileged)
            self.assertIn("-C", command.args)

    def test_store_failure_includes_guidance_and_original_diagnostic(self):
        self.window.demo = None
        diagnostics = [
            "ValueError: SELinux policy is not managed or store cannot be accessed.",
            "libsemanage.semanage_create_store: Could not read from module store (Permission denied).",
        ]
        for diagnostic in diagnostics:
            with self.subTest(error=diagnostic), patch("app.launch_arguments", return_value=(sys.executable, ["-c", "import sys; print(" + repr(diagnostic) + ", file=sys.stderr); sys.exit(1)"])), patch.object(QMessageBox, "warning") as warning:
                self.window.run(Command("semanage", ("port", "-l"), True), lambda output: self.fail("Unexpected success"))
                self.wait_idle()
                message = warning.call_args.args[2]
                self.assertIn("administrator access automatically", message)
                self.assertIn(diagnostic, message)
                self.assertIn(diagnostic, self.window.log.toPlainText())

    def test_confirmed_mutation_refresh_and_cancel(self):
        self.window.navigation.setCurrentRow(1)
        self.wait_idle()
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Apply):
            self.window.apply(lambda: boolean_command("virt_use_nfs", True, True), "Test change", 1)
        self.wait_idle()
        self.assertEqual(self.window.demo.booleans["virt_use_nfs"], "on")
        self.assertTrue(self.window.workspace.isEnabled())
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel):
            self.window.apply(lambda: boolean_command("virt_use_nfs", False, True), "Cancel test", 1)
        self.assertEqual(self.window.demo.booleans["virt_use_nfs"], "on")

    def test_table_refresh_with_selection(self):
        self.window.navigation.setCurrentRow(1)
        self.wait_idle()
        self.window.booleans.setCurrentCell(0, 0)
        self.window.refresh(1)
        self.wait_idle()
        self.assertEqual(self.window.booleans.rowCount(), 5)
        self.window.navigation.setCurrentRow(2)
        self.wait_idle()
        self.window.ports_table.setCurrentCell(0, 0)
        self.window.refresh(2)
        self.wait_idle()
        self.assertGreater(self.window.ports_table.rowCount(), 0)

    def test_real_process_success_and_failure(self):
        self.window.demo = None
        outputs = []
        with patch("app.launch_arguments", return_value=(sys.executable, ["-c", "import sys; assert sys.stdin.read() == ''; print('process result')"])):
            self.window.run(Command("sestatus"), outputs.append)
            self.wait_idle()
        self.assertEqual(outputs, ["process result\n"])
        with patch("app.launch_arguments", return_value=(sys.executable, ["-c", "import sys; print('rejected', file=sys.stderr); sys.exit(7)"])), patch.object(QMessageBox, "warning") as warning:
            self.window.run(Command("sestatus"), outputs.append)
            self.wait_idle()
            self.assertIn("rejected", warning.call_args.args[2])
            self.assertIn("Exit code: 7", warning.call_args.args[2])
        self.assertEqual(len(outputs), 1)
        self.assertTrue(self.window.workspace.isEnabled())

    def test_missing_executable_and_failed_start(self):
        self.window.demo = None
        with patch("app.launch_arguments", side_effect=FileNotFoundError("Missing tool")), patch.object(QMessageBox, "warning") as warning:
            self.window.run(Command("sestatus"), lambda output: self.fail("Unexpected success"))
            self.assertIn("Missing tool", warning.call_args.args[2])
        with patch("app.launch_arguments", return_value=("/nonexistent-selinux-manager-executable", [])), patch.object(QMessageBox, "warning") as warning:
            self.window.run(Command("sestatus"), lambda output: self.fail("Unexpected success"))
            self.wait_idle()
            self.assertTrue(warning.called)

    def test_audit_no_matches_is_success(self):
        self.window.demo = None
        outputs = []
        with patch("app.launch_arguments", return_value=(sys.executable, ["-c", "import sys; print('<no matches>', file=sys.stderr); sys.exit(1)"])):
            self.window.run(Command("ausearch"), outputs.append)
            self.wait_idle()
        self.assertEqual(outputs, ["No matching audit events.\n"])

    def test_close_blocked_during_command(self):
        self.window.run(Command("sestatus"), lambda output: None)
        self.window.close()
        self.assertTrue(self.window.isVisible())
        self.wait_idle()
        self.window.close()
        self.assertFalse(self.window.isVisible())

    def test_audit_read_errors_not_hidden_by_no_matches(self):
        self.window.demo = None
        with patch("app.launch_arguments", return_value=(sys.executable, ["-c", "import sys; print('<no matches>'); print('Permission denied', file=sys.stderr); sys.exit(1)"])), patch.object(QMessageBox, "warning") as warning:
            self.window.run(Command("ausearch"), lambda output: self.fail("Unexpected success"))
            self.wait_idle()
            self.assertIn("Permission denied", warning.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
