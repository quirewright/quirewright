"""Minimal affine geometry used by the core (kept independent of Qt and MuPDF).

Conventions follow the PDF specification: points are row vectors and a
matrix ``[a b c d e f]`` maps ``(x, y)`` to ``(a*x + c*y + e, b*x + d*y + f)``.
``M1 * M2`` applies ``M1`` first, then ``M2`` (same as PDF ``cm`` semantics,
where the new CTM is ``cm_matrix * CTM``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Matrix:
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @staticmethod
    def identity() -> "Matrix":
        return Matrix()

    @staticmethod
    def translation(tx: float, ty: float) -> "Matrix":
        return Matrix(1, 0, 0, 1, tx, ty)

    @staticmethod
    def scale(sx: float, sy: float | None = None) -> "Matrix":
        if sy is None:
            sy = sx
        return Matrix(sx, 0, 0, sy, 0, 0)

    @staticmethod
    def rotation(degrees: float) -> "Matrix":
        r = math.radians(degrees)
        c, s = math.cos(r), math.sin(r)
        return Matrix(c, s, -s, c, 0, 0)

    def __mul__(self, other: "Matrix") -> "Matrix":
        """self first, then other."""
        return Matrix(
            self.a * other.a + self.b * other.c,
            self.a * other.b + self.b * other.d,
            self.c * other.a + self.d * other.c,
            self.c * other.b + self.d * other.d,
            self.e * other.a + self.f * other.c + other.e,
            self.e * other.b + self.f * other.d + other.f,
        )

    def det(self) -> float:
        return self.a * self.d - self.b * self.c

    def inverted(self) -> "Matrix":
        det = self.det()
        if abs(det) < 1e-12:
            raise ValueError("matrix is singular")
        ia = self.d / det
        ib = -self.b / det
        ic = -self.c / det
        id_ = self.a / det
        ie = -(self.e * ia + self.f * ic)
        if_ = -(self.e * ib + self.f * id_)
        return Matrix(ia, ib, ic, id_, ie, if_)

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def apply_vector(self, x: float, y: float) -> tuple[float, float]:
        """Transform a direction (ignores translation)."""
        return (self.a * x + self.c * y, self.b * x + self.d * y)

    def expansion(self) -> float:
        """Geometric mean scale factor (sqrt of |det|)."""
        return math.sqrt(abs(self.det()))

    def is_uniform_scale(self, tol: float = 1e-6) -> bool:
        """True if the matrix is a similarity (uniform scale + rotation)."""
        return abs(self.a - self.d) <= tol and abs(self.b + self.c) <= tol

    def is_identity(self, tol: float = 1e-9) -> bool:
        return (
            abs(self.a - 1) <= tol
            and abs(self.b) <= tol
            and abs(self.c) <= tol
            and abs(self.d - 1) <= tol
            and abs(self.e) <= tol
            and abs(self.f) <= tol
        )

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (self.a, self.b, self.c, self.d, self.e, self.f)


@dataclass(frozen=True, slots=True)
class Rect:
    """Axis-aligned rectangle with x0 <= x1 and y0 <= y1."""

    x0: float
    y0: float
    x1: float
    y1: float

    @staticmethod
    def from_points(points: Iterable[tuple[float, float]]) -> "Rect | None":
        pts = list(points)
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return Rect(min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def normalized(x0: float, y0: float, x1: float, y1: float) -> "Rect":
        return Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def is_empty(self) -> bool:
        return self.x1 <= self.x0 or self.y1 <= self.y0

    def union(self, other: "Rect | None") -> "Rect":
        if other is None:
            return self
        return Rect(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def intersect(self, other: "Rect | None") -> "Rect":
        if other is None:
            return self
        return Rect(
            max(self.x0, other.x0),
            max(self.y0, other.y0),
            min(self.x1, other.x1),
            min(self.y1, other.y1),
        )

    def expanded(self, margin: float) -> "Rect":
        return Rect(self.x0 - margin, self.y0 - margin, self.x1 + margin, self.y1 + margin)

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def transformed(self, m: Matrix) -> "Rect":
        """Bounding box of this rect after transformation."""
        corners = [
            m.apply(self.x0, self.y0),
            m.apply(self.x1, self.y0),
            m.apply(self.x1, self.y1),
            m.apply(self.x0, self.y1),
        ]
        return Rect.from_points(corners)  # type: ignore[return-value]

    def corners(self) -> list[tuple[float, float]]:
        return [(self.x0, self.y0), (self.x1, self.y0), (self.x1, self.y1), (self.x0, self.y1)]


def union_rects(rects: Iterable[Rect | None]) -> Rect | None:
    out: Rect | None = None
    for r in rects:
        if r is None:
            continue
        out = r if out is None else out.union(r)
    return out
