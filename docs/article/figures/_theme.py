"""Shared drawing primitives for the article figures.

Hand-authoring six consistent SVGs is a losing game: the third one drifts from
the first and nobody notices until they are side by side in a published piece.
So the figures are described declaratively and drawn by the primitives here,
which makes the palette, the type scale and the arrowheads the same by
construction rather than by care.

Colour carries an argument in these diagrams and is not decoration:

    teal    deterministic code, which cannot be talked out of a decision
    violet  the model, drawn dashed everywhere it appears
    red     a refusal
    amber   a person
    slate   the record
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent

FONT = "Segoe UI, -apple-system, BlinkMacSystemFont, Inter, Roboto, Helvetica, Arial, sans-serif"
MONO = "Cascadia Mono, Consolas, SF Mono, Menlo, DejaVu Sans Mono, monospace"

INK = "#1c1917"
MUTED = "#78716c"
FAINT = "#a8a29e"
PAGE = "#ffffff"
PANEL = "#fafaf9"
LINE = "#d6d3d1"

TEAL = "#0f766e"
TEAL_FILL = "#f0fdfa"
TEAL_EDGE = "#5eead4"

VIOLET = "#6d28d9"
VIOLET_FILL = "#f5f3ff"
VIOLET_EDGE = "#c4b5fd"

RED = "#b91c1c"
RED_FILL = "#fef2f2"
RED_EDGE = "#fca5a5"

AMBER = "#b45309"
AMBER_FILL = "#fffbeb"
AMBER_EDGE = "#fcd34d"

SLATE = "#334155"
SLATE_FILL = "#f8fafc"
SLATE_EDGE = "#cbd5e1"

# Rough advance widths as a fraction of the font size. Good enough to centre a
# label in a box and to size a box around a label; not good enough to justify.
_W_REGULAR = 0.515
_W_BOLD = 0.545
_W_MONO = 0.600
_NARROW = "iljtfrI.,:;|()[]/ "


def text_width(s: str, size: float, *, bold: bool = False, mono: bool = False) -> float:
    factor = _W_MONO if mono else (_W_BOLD if bold else _W_REGULAR)
    if mono:
        return len(s) * size * factor
    narrow = sum(1 for c in s if c in _NARROW)
    upper = sum(1 for c in s if c.isupper())
    return (len(s) - narrow * 0.42 + upper * 0.13) * size * factor


@dataclass
class Canvas:
    width: float
    height: float
    parts: list[str] = field(default_factory=list)

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str = PAGE,
        stroke: str = LINE,
        width: float = 1.5,
        radius: float = 10,
        dash: str | None = None,
        opacity: float = 1.0,
    ) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        o = f' opacity="{opacity}"' if opacity != 1.0 else ""
        self.add(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{radius}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{width}"{d}{o}/>'
        )

    def text(
        self,
        x: float,
        y: float,
        s: str,
        *,
        size: float = 15,
        fill: str = INK,
        anchor: str = "start",
        bold: bool = False,
        mono: bool = False,
        italic: bool = False,
        opacity: float = 1.0,
        spacing: float | None = None,
    ) -> None:
        family = MONO if mono else FONT
        weight = ' font-weight="600"' if bold else ""
        style = ' font-style="italic"' if italic else ""
        o = f' opacity="{opacity}"' if opacity != 1.0 else ""
        ls = f' letter-spacing="{spacing}"' if spacing is not None else ""
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}"{weight}{style}{ls}{o}>{escape(s)}</text>'
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = MUTED,
        width: float = 1.5,
        dash: str | None = None,
        arrow: str | None = None,
        opacity: float = 1.0,
    ) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        a = f' marker-end="url(#{arrow})"' if arrow else ""
        o = f' opacity="{opacity}"' if opacity != 1.0 else ""
        self.add(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{width}" stroke-linecap="round"{d}{a}{o}/>'
        )

    def path(
        self,
        d: str,
        *,
        stroke: str = MUTED,
        width: float = 1.5,
        dash: str | None = None,
        arrow: str | None = None,
        fill: str = "none",
        opacity: float = 1.0,
    ) -> None:
        da = f' stroke-dasharray="{dash}"' if dash else ""
        a = f' marker-end="url(#{arrow})"' if arrow else ""
        o = f' opacity="{opacity}"' if opacity != 1.0 else ""
        self.add(
            f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round"{da}{a}{o}/>'
        )

    def label_box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        lines: list[tuple[str, dict]],
        *,
        fill: str = PAGE,
        stroke: str = LINE,
        dash: str | None = None,
        radius: float = 10,
        stroke_width: float = 1.5,
        leading: float = 17,
    ) -> None:
        """A box with vertically centred lines of text."""
        self.box(x, y, w, h, fill=fill, stroke=stroke, dash=dash, radius=radius, width=stroke_width)
        total = leading * (len(lines) - 1)
        first = y + h / 2 - total / 2
        for i, (s, opts) in enumerate(lines):
            size = opts.get("size", 14)
            self.text(
                x + w / 2,
                first + i * leading + size * 0.35,
                s,
                anchor="middle",
                size=size,
                fill=opts.get("fill", INK),
                bold=opts.get("bold", False),
                mono=opts.get("mono", False),
                italic=opts.get("italic", False),
            )

    def pill(
        self,
        cx: float,
        y: float,
        s: str,
        *,
        size: float = 12,
        fill: str = PANEL,
        stroke: str = LINE,
        ink: str = MUTED,
        bold: bool = False,
        mono: bool = False,
        pad: float = 11,
    ) -> float:
        w = text_width(s, size, bold=bold, mono=mono) + pad * 2
        h = size + 12
        self.box(cx - w / 2, y, w, h, fill=fill, stroke=stroke, radius=h / 2, width=1.2)
        self.text(
            cx,
            y + h / 2 + size * 0.35,
            s,
            size=size,
            fill=ink,
            anchor="middle",
            bold=bold,
            mono=mono,
        )
        return w

    def vtext(
        self,
        x: float,
        y: float,
        s: str,
        *,
        size: float = 11,
        fill: str = MUTED,
        anchor: str = "middle",
        bold: bool = False,
    ) -> None:
        """Text rotated to run up a vertical rail."""
        weight = ' font-weight="600"' if bold else ""
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}"{weight} '
            f'transform="rotate(-90 {x:.1f} {y:.1f})">{escape(s)}</text>'
        )

    def render(self) -> str:
        arrows = "\n    ".join(
            f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" '
            f'markerHeight="6.5" orient="auto-start-reverse">'
            f'<path d="M 0 1 L 9 5 L 0 9 z" fill="{colour}"/></marker>'
            for name, colour in (
                ("a", MUTED),
                ("a-teal", TEAL),
                ("a-red", RED),
                ("a-amber", AMBER),
                ("a-violet", VIOLET),
                ("a-faint", FAINT),
                ("a-slate", SLATE),
            )
        )
        body = "\n  ".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:.0f}" '
            f'height="{self.height:.0f}" viewBox="0 0 {self.width:.0f} {self.height:.0f}">\n'
            f'  <rect width="{self.width:.0f}" height="{self.height:.0f}" fill="{PAGE}"/>\n'
            f"  <defs>\n    {arrows}\n  </defs>\n"
            f"  {body}\n</svg>\n"
        )

    def save(self, name: str) -> Path:
        path = HERE / f"{name}.svg"
        path.write_text(self.render(), encoding="utf-8")
        return path


def title(c: Canvas, x: float, y: float, heading: str, sub: str | None = None) -> None:
    c.text(x, y, heading, size=21, bold=True)
    if sub:
        c.text(x, y + 25, sub, size=14.5, fill=MUTED)


def legend(c: Canvas, x: float, y: float, entries: list[tuple[str, str, bool]]) -> None:
    """entries: (colour, label, dashed)"""
    cursor = x
    for colour, label, dashed in entries:
        c.box(
            cursor,
            y - 8,
            26,
            14,
            fill=PAGE,
            stroke=colour,
            width=2,
            radius=4,
            dash="4 3" if dashed else None,
        )
        c.text(cursor + 34, y + 3.5, label, size=13, fill=MUTED)
        cursor += 34 + text_width(label, 13) + 30
