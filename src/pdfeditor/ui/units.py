"""Length units for display: points are the internal unit everywhere."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDoubleSpinBox

from pdfeditor import APP_ID

UNITS = {"pt": 1.0, "mm": 72.0 / 25.4, "cm": 72.0 / 2.54, "in": 72.0, "px": 1.0}
UNIT_DECIMALS = {"pt": 2, "mm": 2, "cm": 3, "in": 3, "px": 1}


def current_unit() -> str:
    u = QSettings(APP_ID, APP_ID).value("ui/units", "pt")
    return u if u in UNITS else "pt"


def set_current_unit(unit: str) -> None:
    if unit in UNITS:
        QSettings(APP_ID, APP_ID).setValue("ui/units", unit)


def pt_to_unit(value_pt: float, unit: str | None = None) -> float:
    unit = unit or current_unit()
    return value_pt / UNITS[unit]


def unit_to_pt(value: float, unit: str | None = None) -> float:
    unit = unit or current_unit()
    return value * UNITS[unit]


def format_length(value_pt: float, unit: str | None = None) -> str:
    unit = unit or current_unit()
    return f"{pt_to_unit(value_pt, unit):.{UNIT_DECIMALS[unit]}f} {unit}"


class LengthSpin(QDoubleSpinBox):
    """A spin box that shows lengths in the user's unit but stores points."""

    def __init__(self, minimum_pt: float = -1e5, maximum_pt: float = 1e5, step_pt: float = 1.0, parent=None):
        super().__init__(parent)
        self._unit = current_unit()
        self._min_pt, self._max_pt, self._step_pt = minimum_pt, maximum_pt, step_pt
        self.setKeyboardTracking(False)
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.refresh_unit()

    def refresh_unit(self) -> None:
        pt = self.value_pt() if self.maximum() else 0.0
        self._unit = current_unit()
        self.setDecimals(UNIT_DECIMALS[self._unit])
        self.setSuffix(" " + self._unit)
        self.setRange(pt_to_unit(self._min_pt, self._unit), pt_to_unit(self._max_pt, self._unit))
        self.setSingleStep(pt_to_unit(self._step_pt, self._unit) if self._unit == "pt" else {"mm": 1, "cm": 0.1, "in": 0.1, "px": 1}[self._unit])
        self.set_value_pt(pt)

    def value_pt(self) -> float:
        return unit_to_pt(self.value(), self._unit)

    def set_value_pt(self, pt: float) -> None:
        self.setValue(pt_to_unit(pt, self._unit))
