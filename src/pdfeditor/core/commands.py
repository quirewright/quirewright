"""Undo/redo support for document edits.

Two kinds of commands exist: content-stream edits (store the old and new
stream for one page; cheap) and whole-document snapshots (used for page
structure operations where the inverse is awkward to express).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover
    from pdfeditor.core.document import Document


class Command:
    label: str

    def redo(self, doc: "Document") -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def undo(self, doc: "Document") -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def merge_with(self, other: "Command") -> bool:
        return False


@dataclass
class ContentEditCommand(Command):
    label: str
    page_index: int
    old_stream: bytes
    new_stream: bytes
    page_xref: int = 0

    def redo(self, doc: "Document") -> None:
        doc._write_stream(self.page_index, self.new_stream)

    def undo(self, doc: "Document") -> None:
        doc._write_stream(self.page_index, self.old_stream)


@dataclass
class SnapshotCommand(Command):
    label: str
    before: bytes
    after: bytes | None = None
    action: Callable[["Document"], None] | None = None

    def redo(self, doc: "Document") -> None:
        if self.after is None:
            assert self.action is not None
            self.action(doc)
            self.after = doc.snapshot()
            doc._after_structure_change()
        else:
            doc.restore(self.after)

    def undo(self, doc: "Document") -> None:
        doc.restore(self.before)


@dataclass
class UndoStack:
    doc: "Document"
    limit: int = 100
    _undo: list[Command] = field(default_factory=list)
    _redo: list[Command] = field(default_factory=list)
    listeners: list[Callable[[], None]] = field(default_factory=list)
    clean_index: int = 0

    def push(self, cmd: Command) -> None:
        cmd.redo(self.doc)
        self._undo.append(cmd)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
            self.clean_index = max(-1, self.clean_index - 1)
        self._redo.clear()
        self._notify()

    def undo(self) -> None:
        if not self._undo:
            return
        cmd = self._undo.pop()
        cmd.undo(self.doc)
        self._redo.append(cmd)
        self._notify()

    def redo(self) -> None:
        if not self._redo:
            return
        cmd = self._redo.pop()
        cmd.redo(self.doc)
        self._undo.append(cmd)
        self._notify()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str:
        return self._undo[-1].label if self._undo else ""

    @property
    def redo_label(self) -> str:
        return self._redo[-1].label if self._redo else ""

    @property
    def is_clean(self) -> bool:
        return len(self._undo) == self.clean_index

    def mark_clean(self) -> None:
        self.clean_index = len(self._undo)
        self._notify()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self.clean_index = 0
        self._notify()

    def _notify(self) -> None:
        for cb in list(self.listeners):
            cb()
