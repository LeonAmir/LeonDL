from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from core.theme_tokens import THEME_TOKENS, normalize_theme_name


@dataclass(frozen=True)
class Theme:
    name: str
    display_name: str
    display_name_en: str
    dark: bool
    background_a: str
    background_b: str
    background_c: str
    surface: str
    glass: str
    glass_strong: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    accent_text: str
    success: str
    danger: str
    warning: str
    input_bg: str
    input_focus: str
    control_hover: str
    progress_bg: str
    scroll_handle: str
    primary_start: str
    primary_end: str

    def label(self, language: str = "fa") -> str:
        return self.display_name_en if language == "en" else self.display_name


THEMES: "OrderedDict[str, Theme]" = OrderedDict(
    (name, Theme(**tokens)) for name, tokens in THEME_TOKENS.items()
)
AURORA = THEMES["aurora"]
OBSIDIAN = THEMES["obsidian"]
ROYAL_NAVY = THEMES["royal_navy"]
LIGHT = THEMES["light"]
YOUTUBE = THEMES["youtube"]

# Backward-compatible aliases for old settings/imports.
MIDNIGHT = OBSIDIAN
PEARL = ROYAL_NAVY


def theme_from_name(name: str | None) -> Theme:
    return THEMES[normalize_theme_name(name)]


def build_message_box_stylesheet(theme: Theme) -> str:
    """Return a self-contained dialog stylesheet that stays readable on Windows.

    Qt message boxes may otherwise keep a light platform background while the
    application-wide wildcard rule paints their labels with a light theme text
    color. Applying this stylesheet explicitly prevents white-on-white dialogs.
    """
    return f"""
    QMessageBox {{
        background: {theme.surface};
        color: {theme.text};
    }}
    QMessageBox QLabel {{
        color: {theme.text};
        background: transparent;
        font-size: 9.5pt;
    }}
    QMessageBox QTextEdit, QMessageBox QPlainTextEdit {{
        color: {theme.text};
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 9px;
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}
    QMessageBox QPushButton {{
        color: {theme.text};
        background: {theme.glass_strong};
        border: 1px solid {theme.border};
        border-radius: 9px;
        padding: 7px 14px;
        min-width: 88px;
        min-height: 20px;
        font-weight: 800;
    }}
    QMessageBox QPushButton:hover {{
        background: {theme.control_hover};
        border-color: {theme.accent_hover};
    }}
    """


def build_stylesheet(theme: Theme) -> str:
    return f"""
    * {{
        font-family: "Vazir", "Vazirmatn", "Segoe UI Variable", "Segoe UI", "Tahoma";
        font-size: 9.25pt;
        color: {theme.text};
    }}

    QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget,
    QSplitter, QStackedWidget {{ background: transparent; }}

    QFrame#windowSurface {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {theme.background_a}, stop:0.53 {theme.background_b}, stop:1 {theme.background_c});
        border: 1px solid {theme.border};
        border-radius: 15px;
    }}

    QFrame#titleBar {{ background: transparent; }}
    QLabel#appTitle {{ font-size: 17.2pt; font-weight: 950; color: {theme.accent_soft}; letter-spacing: .3px; }}
    QLabel#appSubtitle {{ color: {theme.muted}; font-size: 8.35pt; font-weight: 600; }}
    QLabel#versionBadge {{
        color: {theme.accent};
        background: {theme.control_hover};
        border: 1px solid {theme.border};
        border-radius: 9px;
        padding: 4px 8px;
        font-size: 7.4pt;
        font-weight: 900;
        letter-spacing: 1px;
    }}


    QFrame#commandBar {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {theme.glass_strong}, stop:0.55 {theme.surface}, stop:1 {theme.glass});
        border: 1px solid {theme.border};
        border-radius: 16px;
    }}
    QFrame#commandBar QFrame#quickStat {{
        background: {theme.input_bg};
        border-radius: 11px;
        min-height: 36px;
    }}

    QFrame#heroCard {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {theme.glass_strong}, stop:0.58 {theme.glass}, stop:1 {theme.surface});
        border: 1px solid {theme.accent};
        border-radius: 20px;
    }}
    QFrame#heroCard[hovered="true"] {{ border-color: {theme.accent_hover}; }}
    QLabel#heroBadge {{
        color: {theme.accent_text};
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {theme.primary_start}, stop:1 {theme.accent});
        border: 1px solid {theme.accent_hover};
        border-radius: 10px;
        padding: 5px 11px;
        font-size: 8pt;
        font-weight: 950;
        letter-spacing: 1.1px;
    }}
    QLabel#heroTitle {{ font-size: 16.5pt; font-weight: 950; color: {theme.accent_soft}; }}
    QLabel#heroSupport {{ color: {theme.accent}; font-size: 8.35pt; font-weight: 850; }}
    QLabel#heroHint {{ color: {theme.muted}; font-size: 8pt; }}

    QFrame#quickStat, QFrame#quickPresetPicker {{
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 12px;
        min-height: 41px;
    }}
    QFrame#quickStat:hover, QFrame#quickPresetPicker:hover {{
        background: {theme.input_focus};
        border-color: {theme.accent_hover};
    }}
    QLabel#quickStatTitle {{ color: {theme.muted}; font-size: 7.8pt; font-weight: 750; }}
    QLabel#quickStatValue {{ color: {theme.accent_soft}; font-size: 9.3pt; font-weight: 950; }}
    QComboBox#heroPresetCombo {{
        color: {theme.accent_soft};
        background: transparent;
        border: 0;
        border-radius: 6px;
        padding: 1px 4px;
        min-height: 16px;
        font-size: 8.5pt;
        font-weight: 900;
    }}
    QComboBox#heroPresetCombo:hover {{ background: {theme.control_hover}; border: 0; }}
    QComboBox#heroPresetCombo:focus {{ background: {theme.control_hover}; border: 0; }}

    QFrame[glass="true"] {{
        background: {theme.glass};
        border: 1px solid {theme.border};
        border-radius: 14px;
    }}
    QFrame[glass="true"][hovered="true"] {{
        background: {theme.glass_strong};
    }}
    QFrame[glassStrong="true"] {{
        background: {theme.glass_strong};
        border: 1px solid {theme.border};
        border-radius: 16px;
    }}
    QFrame[glassStrong="true"][hovered="true"] {{ border-color: {theme.accent_hover}; }}

    QLabel#sectionTitle {{ font-size: 11.1pt; font-weight: 950; color: {theme.accent_soft}; }}
    QLabel#muted, QLabel[muted="true"] {{ color: {theme.muted}; }}
    QLabel#accent {{ color: {theme.accent}; font-weight: 950; }}
    QLabel#previewTitle {{ font-size: 12pt; font-weight: 950; }}
    QLabel#statusTitle {{ font-size: 13.1pt; font-weight: 950; color: {theme.accent_soft}; }}
    QLabel#statValue {{ font-size: 10.3pt; font-weight: 950; color: {theme.accent_soft}; }}
    QLabel#statTitle {{ color: {theme.muted}; font-size: 8.3pt; font-weight: 800; }}
    QLabel[fieldLabel="true"] {{ font-size: 8.7pt; font-weight: 850; }}
    QLabel[compactHint="true"] {{ font-size: 8.2pt; }}

    QLabel#serviceBadge, QLabel#serviceBadgeMuted {{
        border-radius: 9px;
        padding: 4px 9px;
        font-size: 8.2pt;
        font-weight: 950;
    }}
    QLabel#serviceBadge {{
        color: {theme.accent_text};
        background: {theme.accent};
        border: 1px solid {theme.accent_hover};
    }}
    QLabel#serviceBadgeMuted {{
        color: {theme.accent_soft};
        background: {theme.control_hover};
        border: 1px solid {theme.border};
    }}

    QLabel#runtimeStatus {{
        color: {theme.muted};
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 13px;
        padding: 11px 13px;
    }}
    QLabel#runtimeStatus[runtimeOk="true"] {{ color: {theme.success}; border-color: {theme.success}; }}
    QLabel#runtimeStatus[runtimeOk="false"] {{ color: {theme.warning}; border-color: {theme.warning}; }}

    QLabel#authProfileStatus {{
        color: {theme.muted};
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 12px;
        padding: 9px 12px;
        font-size: 8pt;
        font-weight: 700;
    }}
    QLabel#authProfileStatus[authProfileState="ready"] {{ color: {theme.success}; border-color: {theme.success}; }}
    QLabel#authProfileStatus[authProfileState="warning"] {{ color: {theme.warning}; border-color: {theme.warning}; }}

    QScrollArea#previewListScroll {{ background: transparent; border: none; }}
    QFrame[previewItem="true"] {{
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 15px;
    }}
    QFrame[previewItem="true"]:hover {{ background: {theme.input_focus}; border-color: {theme.accent_hover}; }}
    QPushButton#removePreviewButton {{
        background: transparent; border: 1px solid transparent; border-radius: 13px;
        min-width: 0; min-height: 0; padding: 0; font-size: 15pt; color: {theme.muted};
    }}
    QPushButton#removePreviewButton:hover, QPushButton#removePreviewButton:focus {{
        background: {theme.control_hover}; border-color: {theme.border}; color: {theme.danger};
    }}
    QLabel#previewThumb {{
        color: {theme.muted};
        background: {theme.surface};
        border: 1px solid {theme.border};
        border-radius: 14px;
    }}
    QLabel#previewItemTitle {{ font-size: 10.3pt; font-weight: 950; color: {theme.text}; }}
    QLabel#previewItemMeta {{ font-size: 8.6pt; color: {theme.muted}; }}
    QLabel#previewItemAudio, QLabel#previewItemSubtitles {{
        font-size: 8.3pt;
        color: {theme.accent};
        background: {theme.control_hover};
        border: 1px solid {theme.border};
        border-radius: 8px;
        padding: 4px 7px;
    }}
    QLabel#previewItemSize {{
        color: {theme.accent_soft};
        font-weight: 850;
        padding: 5px 8px;
        border-radius: 9px;
        background: {theme.control_hover};
        border: 1px solid {theme.border};
    }}
    QLabel#previewItemSize[sizeConfidence="exact"] {{ color: {theme.success}; border-color: {theme.success}; }}
    QLabel#previewItemSize[sizeConfidence="estimated"] {{ color: {theme.warning}; border-color: {theme.warning}; }}
    QLabel#previewItemSize[sizeConfidence="unknown"] {{ color: {theme.muted}; background: {theme.input_bg}; }}
    QLabel#previewSizeSummary {{ color: {theme.accent}; font-weight: 850; padding: 4px 2px; }}
    QLabel#previewIndexBadge, QLabel#previewCountBadge, QLabel#previewStatus {{
        border-radius: 8px;
        padding: 4px 8px;
        font-size: 8pt;
        font-weight: 950;
    }}
    QLabel#previewIndexBadge, QLabel#previewCountBadge {{
        color: {theme.accent_soft};
        background: {theme.control_hover};
        border: 1px solid {theme.border};
    }}
    QLabel#previewStatus {{ color: {theme.muted}; background: {theme.surface}; border: 1px solid {theme.border}; }}
    QLabel#previewStatus[previewState="checking"] {{ color: {theme.warning}; border-color: {theme.warning}; }}
    QLabel#previewStatus[previewState="ready"] {{ color: {theme.success}; border-color: {theme.success}; }}
    QLabel#previewStatus[previewState="error"] {{ color: {theme.danger}; border-color: {theme.danger}; }}
    QLabel#previewEmpty {{ color: {theme.muted}; font-weight: 750; }}
    QFrame#previewEmptyPanel {{
        background: {theme.input_bg};
        border: 1px dashed {theme.border};
        border-radius: 14px;
    }}
    QFrame#queueInputPanel {{
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 12px;
    }}

    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 10px;
        padding: 7px 10px;
        min-height: 18px;
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}
    QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {theme.accent}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {theme.accent_hover};
        background: {theme.input_focus};
    }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
        color: {theme.muted};
        background: rgba(127,127,127,14);
    }}

    QListWidget {{
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 11px;
        padding: 6px;
        color: {theme.text};
        selection-background-color: {theme.glass_strong};
        selection-color: {theme.accent_soft};
    }}
    QListWidget:focus {{ border: 1px solid {theme.accent_hover}; background: {theme.input_focus}; }}
    QListWidget::item {{ color: {theme.text}; padding: 8px; margin: 2px; border-radius: 9px; }}
    QListWidget::item:hover {{ background: {theme.control_hover}; }}
    QListWidget::item:selected {{
        color: {theme.text};
        background: {theme.glass_strong};
        border: 1px solid {theme.accent};
    }}

    QPlainTextEdit#logView, QPlainTextEdit#cookieText {{
        font-family: "Vazir", "Vazirmatn", "Tahoma", "Segoe UI";
        font-size: 8.9pt;
    }}

    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
    QComboBox QAbstractItemView, QMenu {{
        background: {theme.surface};
        border: 1px solid {theme.border};
        border-radius: 11px;
        selection-background-color: {theme.control_hover};
        selection-color: {theme.text};
        padding: 5px;
    }}
    QMenu::item {{ min-width: 178px; padding: 7px 24px 7px 12px; border-radius: 7px; }}
    QMenu::item:selected {{ background: {theme.control_hover}; color: {theme.text}; }}
    QMenu::indicator {{ width: 16px; height: 16px; }}
    QMenu::indicator:checked {{ background: {theme.accent}; border: 1px solid {theme.accent_hover}; border-radius: 8px; }}

    QPushButton {{
        background: {theme.glass_strong};
        border: 1px solid {theme.border};
        border-radius: 10px;
        padding: 7px 11px;
        font-weight: 850;
    }}
    QPushButton:hover {{ background: {theme.control_hover}; border-color: {theme.accent_hover}; }}
    QPushButton:pressed {{ padding-top: 8px; padding-bottom: 6px; }}
    QPushButton:disabled {{ color: {theme.muted}; background: rgba(127,127,127,12); }}
    QPushButton[heroAction="true"] {{
        min-width: 138px;
        text-align: left;
        padding: 9px 12px;
        background: {theme.input_bg};
        border-radius: 11px;
    }}
    QPushButton[heroAction="true"]:hover {{ background: {theme.input_focus}; }}

    QPushButton[commandAction="true"] {{
        min-height: 36px;
        padding: 7px 10px;
        background: {theme.input_bg};
        border-radius: 10px;
    }}
    QPushButton[commandAction="true"]:hover, QPushButton[accentAction="true"]:hover {{
        background: {theme.input_focus};
    }}
    QPushButton[accentAction="true"] {{
        color: {theme.accent_soft};
        background: {theme.input_bg};
        border: 1px solid {theme.accent};
    }}
    QPushButton[commandPrimary="true"] {{ min-height: 36px; min-width: 112px; }}
    QPushButton[packageAction="true"] {{
        min-height: 28px;
        min-width: 82px;
        padding: 5px 10px;
        color: {theme.accent_soft};
        background: {theme.input_bg};
        border-color: {theme.accent};
        border-radius: 9px;
    }}
    QPushButton[packageAction="true"]:hover {{ background: {theme.input_focus}; }}
    QPushButton[primary="true"] {{
        color: {theme.accent_text};
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {theme.primary_start}, stop:0.54 {theme.accent}, stop:1 {theme.primary_end});
        border: 1px solid {theme.accent_hover};
        border-radius: 11px;
        padding: 9px 17px;
        font-size: 10pt;
        font-weight: 950;
    }}
    QPushButton[primary="true"]:hover {{ border: 1px solid {theme.accent_soft}; }}
    QPushButton[danger="true"] {{ color: {theme.danger}; }}
    QPushButton[windowButton="true"] {{
        min-width: 35px; max-width: 38px;
        min-height: 35px; max-height: 38px;
        padding: 0;
        border-radius: 10px;
        background: transparent;
    }}
    QPushButton[utilityButton="true"] {{
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        min-width: 44px; max-width: 48px;
        min-height: 44px; max-height: 48px;
        border-radius: 14px;
    }}
    QPushButton[windowButton="true"]:hover {{ background: {theme.control_hover}; border-color: {theme.accent_hover}; }}
    QPushButton[closeButton="true"]:hover {{ background: rgba(225, 45, 65, 58); border-color: {theme.danger}; }}

    QFrame#actionCard {{ border: 1px solid {theme.accent}; }}
    QSplitter#mainSplitter::handle {{ background: transparent; margin: 3px; }}
    QSplitter#mainSplitter::handle:hover {{ background: {theme.control_hover}; border-radius: 4px; }}

    QCheckBox {{ spacing: 9px; min-height: 27px; font-weight: 700; }}
    QCheckBox::indicator {{
        width: 20px; height: 20px;
        border-radius: 7px;
        border: 1px solid {theme.border};
        background: {theme.input_bg};
    }}
    QCheckBox::indicator:hover {{ border-color: {theme.accent_hover}; }}
    QCheckBox::indicator:checked {{ background: {theme.accent}; border-color: {theme.accent_hover}; }}

    QProgressBar {{
        background: {theme.progress_bg};
        border: 1px solid {theme.border};
        border-radius: 10px;
        min-height: 19px;
        text-align: center;
        font-weight: 950;
    }}
    QProgressBar::chunk {{
        border-radius: 9px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {theme.primary_start}, stop:0.55 {theme.accent}, stop:1 {theme.primary_end});
    }}

    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 3px 1px; }}
    QScrollBar::handle:vertical {{ background: {theme.scroll_handle}; border-radius: 5px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {theme.accent}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

    QTabWidget#mainNavigation::pane, QTabWidget#settingsTabs::pane {{
        background: transparent;
        border: 0;
        top: -1px;
    }}
    QTabWidget#mainNavigation > QTabBar::tab {{
        color: {theme.muted};
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 13px;
        padding: 10px 19px;
        margin: 0 3px 7px 3px;
        font-weight: 900;
        min-width: 86px;
    }}
    QTabWidget#mainNavigation > QTabBar::tab:hover {{ color: {theme.text}; border-color: {theme.accent_hover}; background: {theme.control_hover}; }}
    QTabWidget#mainNavigation > QTabBar::tab:selected {{
        color: {theme.accent_text};
        background: {theme.accent};
    }}
    QTabWidget#settingsTabs > QTabBar::tab {{
        color: {theme.muted};
        background: transparent;
        border: 0;
        border-bottom: 2px solid transparent;
        padding: 7px 13px;
        margin: 0 2px 5px 2px;
        font-weight: 850;
    }}
    QTabWidget#settingsTabs > QTabBar::tab:hover {{ color: {theme.text}; background: {theme.control_hover}; border-radius: 9px; }}
    QTabWidget#settingsTabs > QTabBar::tab:selected {{ color: {theme.accent}; border-bottom-color: {theme.accent}; }}

    QFrame#sideNavCard {{
        border: 1px solid {theme.border};
        border-radius: 15px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {theme.glass_strong}, stop:1 {theme.glass});
    }}
    QLabel#sideNavTitle {{ font-size: 10.5pt; font-weight: 950; color: {theme.accent_soft}; }}
    QListWidget#sideNavList {{
        background: transparent;
        border: none;
        padding: 2px;
    }}
    QListWidget#sideNavList::item {{
        color: {theme.muted};
        background: transparent;
        border: none;
        border-radius: 11px;
        padding: 9px 11px;
        margin: 3px 2px;
        min-height: 22px;
        font-weight: 850;
    }}
    QListWidget#sideNavList::item:hover {{
        color: {theme.text};
        background: {theme.control_hover};
    }}
    QListWidget#sideNavList::item:selected {{
        color: {theme.accent_text};
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {theme.primary_start}, stop:0.55 {theme.accent}, stop:1 {theme.primary_end});
    }}
    QListWidget#sideNavList::item:focus {{
        outline: none;
        border: none;
    }}

    QFrame#searchResultCard {{
        background: {theme.glass_strong};
        border: 1px solid {theme.border};
        border-radius: 15px;
    }}
    QFrame#searchResultCard:hover {{ border-color: {theme.accent_hover}; background: {theme.input_focus}; }}
    QLabel#searchThumb {{
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        border-radius: 11px;
        color: {theme.accent};
        font-size: 17pt;
        font-weight: 950;
    }}
    QLabel#searchResultTitle {{ font-size: 10.3pt; font-weight: 950; color: {theme.accent_soft}; }}

    QTableWidget {{
        color: {theme.text};
        background: {theme.input_bg};
        alternate-background-color: {theme.glass};
        border: 1px solid {theme.border};
        border-radius: 14px;
        gridline-color: {theme.border};
        selection-background-color: {theme.control_hover};
        selection-color: {theme.text};
    }}
    QTableWidget::item {{ padding: 7px; }}
    QTableWidget::item:selected {{ color: {theme.text}; background: {theme.control_hover}; }}
    QHeaderView::section {{
        color: {theme.accent_soft};
        background: {theme.glass_strong};
        border: 0;
        border-bottom: 1px solid {theme.border};
        padding: 9px;
        font-weight: 900;
    }}

    QMessageBox {{
        background: {theme.surface};
        color: {theme.text};
    }}
    QMessageBox QLabel {{
        color: {theme.text};
        background: transparent;
    }}
    QMessageBox QTextEdit, QMessageBox QPlainTextEdit {{
        color: {theme.text};
        background: {theme.input_bg};
        border: 1px solid {theme.border};
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}
    QMessageBox QPushButton {{
        color: {theme.text};
        background: {theme.glass_strong};
        border: 1px solid {theme.border};
        min-width: 88px;
    }}

    QToolTip {{
        background: {theme.surface};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 8px;
        padding: 7px;
    }}
    """
