from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QWidget


class AppStyle:
    IS_DEFAULT_THEME = False
    LIGHT_THEME = "light"
    DARK_THEME = "dark"
    BG_COLOR = ""
    FG_COLOR = ""

    @staticmethod
    def get_theme_name():
        return AppStyle.DARK_THEME if AppStyle.IS_DEFAULT_THEME else AppStyle.LIGHT_THEME

    @staticmethod
    def sync_theme_from_application(app: QApplication):
        """Persist the detected app theme in shared style state."""
        window_color = app.palette().color(QPalette.ColorRole.Window)
        AppStyle.IS_DEFAULT_THEME = window_color.lightness() < 128

    @staticmethod
    def sync_theme_from_widget(widget: QWidget):
        """Persist the detected theme from a widget palette."""
        window_color = widget.palette().color(widget.backgroundRole())
        AppStyle.IS_DEFAULT_THEME = window_color.lightness() < 128

    @staticmethod
    def get_stats_widget_colors() -> dict[str, str]:
        """Theme-aware color tokens for StatsWidget."""
        if AppStyle.get_theme_name() == AppStyle.DARK_THEME:
            return {
                "success": "#3ddc84",
                "warning": "#f6ad55",
                "error": "#ff6b6b",
                "default_bg": "#1f1f1f",
                "default_border": "#3d3d3d",
                "success_bg": "#1f4d34",
                "success_border": "#2f6f4b",
            }
        return {
            "success": "#2ecc71",
            "warning": "#f1c40f",
            "error": "#e74c3c",
            "default_bg": "#f0f0f0",
            "default_border": "#cccccc",
            "success_bg": "#e8f5e9",
            "success_border": "#a5d6a7",
        }

    @staticmethod
    def get_translation_highlight_colors() -> dict[str, QColor]:
        """Theme-aware highlight colors for translation status cells."""
        if AppStyle.get_theme_name() == AppStyle.DARK_THEME:
            return {
                "missing": QColor(120, 90, 30),    # deep amber
                "critical": QColor(110, 45, 45),   # deep red
                "style": QColor(120, 80, 50),      # deep orange/brown
            }
        return {
            "missing": QColor(255, 255, 200),      # light yellow
            "critical": QColor(255, 200, 200),     # light red
            "style": QColor(255, 220, 180),        # light orange
        }