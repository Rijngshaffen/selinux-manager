"""App appearance and live desktop color-scheme integration."""
from pathlib import Path
from PyQt6.QtCore import QObject, QSettings, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

try:
    from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusPendingCallWatcher, QDBusPendingReply, QDBusVariant
except ImportError:
    QDBusConnection = None
    QDBusVariant = None

COLORS = {
    "light": dict(bg="#f3f6fb", surface="#ffffff", field="#f8fafd", text="#172b46",
                  muted="#60718a", border="#dbe3ee", accent="#2563eb", hover="#edf3ff",
                  selected="#e8efff", selected_text="#1d4ed8", success="#11795a",
                  success_bg="#e5f5ee", disabled="#93a1b3", stripe="#f9fbfe"),
    "dark": dict(bg="#0c1220", surface="#141e30", field="#101929", text="#e4ebf7",
                 muted="#9aabc5", border="#293952", accent="#6695ff", hover="#1e2f4c",
                 selected="#243b63", selected_text="#bdd3ff", success="#73ddba",
                 success_bg="#173c35", disabled="#61728e", stripe="#172338"),
}


def stylesheet(theme):
    c = COLORS[theme]
    return """
    QWidget {{ color: {text}; font-size: 13px; }}
    QMainWindow, QWidget#appRoot {{ background: {bg}; }}
    QWidget#pageContent {{ background: {surface}; }}
    QWidget#page, QWidget#sidebar, QWidget#activity, QFrame#metric, QFrame#settingsCard {{
        background: {surface}; border: 1px solid {border}; border-radius: 14px;
    }}
    QLabel {{ background: transparent; border: none; }}
    QLabel#title {{ font-size: 27px; font-weight: 700; }}
    QLabel#pageTitle {{ font-size: 23px; font-weight: 700; }}
    QLabel#subtitle, QLabel#eyebrow, QLabel#metricLabel {{ color: {muted}; }}
    QLabel#eyebrow {{ font-size: 11px; font-weight: 700; }}
    QLabel#metricValue {{ font-size: 21px; font-weight: 700; }}
    QLabel#badge {{ background: {success_bg}; color: {success}; border-radius: 9px; padding: 9px 14px; font-weight: 600; }}
    QLabel#notice {{ background: {hover}; color: {muted}; padding: 11px 14px; border-radius: 9px; }}
    QListWidget#navigation {{ background: transparent; border: none; padding: 0; outline: none; }}
    QListWidget::item {{ padding: 12px 10px; border-radius: 8px; margin: 3px 0; }}
    QListWidget::item:hover {{ background: {hover}; }}
    QListWidget::item:selected {{ background: {selected}; color: {selected_text}; font-weight: 600; }}
    QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 9px 14px; font-weight: 500; }}
    QPushButton:hover {{ background: {hover}; border-color: {accent}; }}
    QPushButton:pressed {{ background: {selected}; }}
    QPushButton:focus {{ border: 2px solid {accent}; padding: 8px 13px; }}
    QPushButton:disabled {{ color: {disabled}; background: {field}; border-color: {border}; }}
    QPushButton#primary {{ background: {accent}; color: {primary_text}; border: 1px solid {accent}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {primary_hover}; }}
    QPushButton#primary:disabled {{ background: {selected}; color: {disabled}; border-color: {border}; }}
    QPushButton#themeChoice {{ background: {field}; padding: 16px; font-size: 14px; }}
    QPushButton#themeChoice:checked {{ background: {selected}; color: {selected_text}; border: 2px solid {accent}; padding: 15px; }}
    QLineEdit, QComboBox, QPlainTextEdit, QTableWidget {{
        background: {field}; border: 1px solid {border}; border-radius: 8px; padding: 8px;
        selection-background-color: {selected}; selection-color: {selected_text};
    }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {accent}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {disabled}; }}
    QComboBox {{ min-height: 20px; padding-right: 24px; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{arrow}"); width: 16px; height: 16px; }}
    QComboBox QAbstractItemView {{ background: {surface}; color: {text}; border: 1px solid {border}; selection-background-color: {selected}; selection-color: {selected_text}; }}
    QHeaderView::section {{ background: {surface}; color: {muted}; border: none; border-bottom: 1px solid {border}; padding: 11px; font-weight: 600; }}
    QTableWidget {{ background: {surface}; alternate-background-color: {stripe}; gridline-color: {border}; }}
    QTableWidget::item {{ padding: 5px; border: none; }}
    QTableWidget::item:selected {{ background: {selected}; color: {selected_text}; }}
    QCheckBox {{ spacing: 8px; background: transparent; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {muted}; border-radius: 4px; background: {field}; }}
    QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: url("{check}"); }}
    QCheckBox::indicator:hover {{ border-color: {accent}; }}
    QCheckBox::indicator:disabled {{ border-color: {border}; }}
    QStatusBar {{ background: {bg}; color: {muted}; font-size: 12px; }}
    QSplitter::handle {{ background: transparent; height: 8px; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px; }}
    QScrollBar::handle:vertical {{ background: {border}; min-height: 24px; border-radius: 3px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 6px; }}
    QMessageBox, QDialog {{ background: {surface}; }}
    """.format(**c, primary_text="#ffffff" if theme == "light" else "#0b1730",
               primary_hover="#1d4ed8" if theme == "light" else "#8bb0ff",
               arrow=(Path(__file__).parent / "assets" / f"chevron-{theme}.svg").as_posix(),
               check=(Path(__file__).parent / "assets" / f"check-{theme}.svg").as_posix())


class ThemeController(QObject):
    changed = pyqtSignal(str)

    def __init__(self, app, settings=None, connect_platform=True):
        super().__init__(app)
        self.app = app
        self.settings = settings if settings is not None else QSettings("SELinuxManager", "SELinuxManager")
        preference = self.settings.value("appearance/theme", "system")
        self.preference = preference if preference in ("system", "light", "dark") else "system"
        self.system_scheme = app.styleHints().colorScheme()
        self.portal_scheme = None
        self.fallback = "dark" if app.palette().color(QPalette.ColorRole.Window).lightness() < 128 else "light"
        self.effective = None
        if connect_platform:
            app.styleHints().colorSchemeChanged.connect(self.system_changed)
            self.connect_portal()
        self.apply()

    def set_preference(self, preference):
        if preference not in ("system", "light", "dark"):
            raise ValueError("Unknown theme preference")
        self.preference = preference
        self.settings.setValue("appearance/theme", preference)
        self.settings.sync()
        self.apply()

    def system_changed(self, scheme):
        self.system_scheme = scheme
        self.apply()

    def desktop_theme(self):
        # The portal is a direct desktop preference, including GNOME sessions
        # where the Qt platform plugin reports an unknown color scheme.
        if self.portal_scheme is not None:
            return self.portal_scheme
        if self.system_scheme == Qt.ColorScheme.Dark:
            return "dark"
        if self.system_scheme == Qt.ColorScheme.Light:
            return "light"
        return self.fallback

    def apply(self):
        theme = self.desktop_theme() if self.preference == "system" else self.preference
        c = COLORS[theme]
        palette = QPalette()
        for role, color in {
            QPalette.ColorRole.Window: c["bg"], QPalette.ColorRole.WindowText: c["text"],
            QPalette.ColorRole.Base: c["field"], QPalette.ColorRole.AlternateBase: c["stripe"],
            QPalette.ColorRole.Text: c["text"], QPalette.ColorRole.Button: c["surface"],
            QPalette.ColorRole.ButtonText: c["text"], QPalette.ColorRole.Highlight: c["selected"],
            QPalette.ColorRole.HighlightedText: c["selected_text"], QPalette.ColorRole.PlaceholderText: c["muted"],
            QPalette.ColorRole.ToolTipBase: c["surface"], QPalette.ColorRole.ToolTipText: c["text"],
            QPalette.ColorRole.Link: c["accent"],
        }.items():
            palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["disabled"]))
        self.app.setPalette(palette)
        self.app.setStyleSheet(stylesheet(theme))
        self.effective = theme
        self.changed.emit(theme)

    def connect_portal(self):
        if QDBusConnection is None:
            return
        self.bus = QDBusConnection.sessionBus()
        if not self.bus.isConnected():
            return
        service, path, interface = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Settings")
        self.bus.connect(service, path, interface, "SettingChanged", self.portal_changed)
        # Read is supported by both older and newer portal versions. Avoid
        # synchronous introspection so a missing portal cannot freeze startup.
        message = QDBusMessage.createMethodCall(service, path, interface, "Read")
        message.setArguments(["org.freedesktop.appearance", "color-scheme"])
        self.watcher = QDBusPendingCallWatcher(self.bus.asyncCall(message, 1500), self)
        self.watcher.finished.connect(self.portal_read)

    def portal_read(self, watcher):
        reply = QDBusPendingReply(watcher).reply()
        if reply.type() != QDBusMessage.MessageType.ErrorMessage and reply.arguments():
            self.update_portal(reply.arguments()[0])
        watcher.deleteLater()

    def update_portal(self, value):
        while QDBusVariant is not None and isinstance(value, QDBusVariant):
            value = value.variant()
        self.portal_scheme = {1: "dark", 2: "light"}.get(value) if isinstance(value, int) else None
        self.apply()

    # QtDBus requires a typed slot to receive the variant-bearing signal.
    if QDBusVariant is not None:
        @pyqtSlot(str, str, QDBusVariant)
        def portal_changed(self, namespace, key, value):
            if namespace == "org.freedesktop.appearance" and key == "color-scheme":
                self.update_portal(value)
