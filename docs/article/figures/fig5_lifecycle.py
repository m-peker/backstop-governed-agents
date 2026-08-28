"""Figure 5 - one refund, from refusal through approval to a safe replay."""

from __future__ import annotations

from _theme import (
    AMBER,
    AMBER_EDGE,
    AMBER_FILL,
    FAINT,
    INK,
    LINE,
    MUTED,
    PAGE,
    PANEL,
    RED,
    SLATE,
    SLATE_EDGE,
    SLATE_FILL,
    TEAL,
    TEAL_EDGE,
    TEAL_FILL,
    VIOLET,
    VIOLET_EDGE,
    VIOLET_FILL,
    Canvas,
    text_width,
    title,
)

W = 1240
H = 1030

LANES = [
    ("LangGraph", 138, VIOLET, VIOLET_FILL, VIOLET_EDGE, True),
    ("Policy engine", 392, TEAL, TEAL_FILL, TEAL_EDGE, False),
    ("Tool gateway", 646, TEAL, TEAL_FILL, TEAL_EDGE, False),
    ("Reviewer", 890, AMBER, AMBER_FILL, AMBER_EDGE, False),
    ("payments", 1122, SLATE, SLATE_FILL, SLATE_EDGE, False),
]
X = {name: x for name, x, *_ in LANES}
GUTTER = 46

TOP = 116
BOTTOM = 932


def message(
    c: Canvas,
    y: float,
    frm: str,
    to: str,
    label: str,
    *,
    colour: str = MUTED,
    arrow: str = "a",
    dash: str | None = None,
    refused: bool = False,
    n: int | None = None,
) -> None:
    x1, x2 = X[frm], X[to]
    direction = 1 if x2 > x1 else -1
    c.line(x1, y, x2 - direction * 7, y, stroke=colour, width=1.6, dash=dash, arrow=arrow)
    if refused:
        mx = (x1 + x2) / 2
        c.line(mx - 7, y - 7, mx + 7, y + 7, stroke=RED, width=2.2)
        c.line(mx + 7, y - 7, mx - 7, y + 7, stroke=RED, width=2.2)
    # The step number lives in its own gutter. Placed inside the span it
    # collides with the label whenever the two lanes are close together.
    if n is not None:
        c.box(GUTTER, y - 9, 22, 18, fill=colour, stroke=colour, radius=5)
        c.text(GUTTER + 11, y + 4, str(n), size=10.5, fill=PAGE, anchor="middle", bold=True)
    c.text((x1 + x2) / 2, y - 11, label, size=11.5, fill=colour, anchor="middle")


def note(
    c: Canvas, y: float, x: float, w: float, lines: list[str], *, colour: str, fill: str
) -> None:
    h = 14 + len(lines) * 16
    c.box(x, y, w, h, fill=fill, stroke=colour, width=1.2, radius=7)
    for i, line in enumerate(lines):
        c.text(x + 12, y + 24 + i * 16, line, size=11, fill=colour)


def build() -> Canvas:
    c = Canvas(W, H)

    title(
        c,
        40,
        46,
        "One refund, refused and then approved",
        "Above the automatic ceiling, so the graph stops. Then it crashes, and the replay does not pay twice.",
    )

    for name, x, colour, fill, _edge, dashed in LANES:
        w = text_width(name, 12.5, bold=True) + 34
        c.box(
            x - w / 2,
            TOP - 34,
            w,
            30,
            fill=fill,
            stroke=colour,
            width=1.5,
            radius=8,
            dash="5 3" if dashed else None,
        )
        c.text(x, TOP - 14, name, size=12.5, fill=colour, anchor="middle", bold=True)
        c.line(x, TOP, x, BOTTOM, stroke=LINE, width=1.2, dash="3 5")

    y = TOP + 42
    step = 52

    message(
        c,
        y,
        "LangGraph",
        "Policy engine",
        "proposal: refund 590.27",
        colour=VIOLET,
        arrow="a-violet",
        n=1,
    )
    y += step
    message(
        c,
        y,
        "Policy engine",
        "LangGraph",
        "REQUIRE_HUMAN  -  RP-4.1 ceiling is 75.00",
        colour=TEAL,
        arrow="a-teal",
        n=2,
    )
    y += step
    message(
        c,
        y,
        "LangGraph",
        "Tool gateway",
        "issue_refund(590.27)",
        colour=VIOLET,
        arrow="a-violet",
        n=3,
    )
    y += step
    message(
        c,
        y,
        "Tool gateway",
        "LangGraph",
        "REFUSED  -  no approval token",
        colour=RED,
        arrow="a-red",
        dash="5 4",
        refused=True,
        n=4,
    )
    note(
        c,
        y + 14,
        X["Tool gateway"] + 40,
        300,
        ["The refusal is appended to the audit chain", "before anything else happens."],
        colour=SLATE,
        fill=SLATE_FILL,
    )
    y += step + 46

    c.line(78, y - 26, W - 60, y - 26, stroke=LINE, width=1, dash="2 6")
    c.text(
        78,
        y - 32,
        "the graph checkpoints and stops - this can last for days",
        size=11,
        fill=MUTED,
        italic=True,
    )

    message(c, y, "LangGraph", "Reviewer", "interrupt()", colour=AMBER, arrow="a-amber", n=5)
    y += step
    message(c, y, "Reviewer", "Tool gateway", "approve", colour=AMBER, arrow="a-amber", n=6)
    y += step
    message(
        c,
        y,
        "Tool gateway",
        "Reviewer",
        "HMAC token bound to ticket + tool + args digest",
        colour=AMBER,
        arrow="a-amber",
        n=7,
    )
    y += step
    message(
        c, y, "Reviewer", "LangGraph", "Command(resume=...)", colour=AMBER, arrow="a-amber", n=8
    )
    y += step + 10

    message(
        c,
        y,
        "LangGraph",
        "Tool gateway",
        "issue_refund(590.27) + token",
        colour=TEAL,
        arrow="a-teal",
        n=9,
    )
    y += step
    message(c, y, "Tool gateway", "payments", "execute", colour=TEAL, arrow="a-teal", n=10)
    y += step
    message(c, y, "payments", "Tool gateway", "ok", colour=SLATE, arrow="a-slate", n=11)
    y += step + 44

    c.line(78, y - 26, W - 60, y - 26, stroke=LINE, width=1, dash="2 6")
    c.text(
        78,
        y - 32,
        "the process crashes and replays the same call",
        size=11,
        fill=MUTED,
        italic=True,
    )
    message(
        c,
        y,
        "LangGraph",
        "Tool gateway",
        "issue_refund(590.27) + token",
        colour=VIOLET,
        arrow="a-violet",
        n=12,
    )
    y += step
    message(
        c,
        y,
        "Tool gateway",
        "LangGraph",
        "replayed  -  money moved exactly once",
        colour=TEAL,
        arrow="a-teal",
        n=13,
    )

    # -- what falls out of this shape --------------------------------------
    fy = BOTTOM + 18
    c.box(40, fy, W - 80, 56, fill=PANEL, stroke=LINE, width=1.5, radius=10)
    c.text(
        58,
        fy + 24,
        "The token is bound to the arguments, not just the ticket, so approving 75.00 would not have authorised 590.27.",
        size=12,
        fill=INK,
    )
    c.text(
        58,
        fy + 43,
        "The idempotency key is derived from the call rather than supplied with it, so step 12 cannot opt out of step 10.",
        size=12,
        fill=INK,
    )

    c.text(
        W - 40, H - 12, "backstop-governed-agents", size=11.5, fill=FAINT, anchor="end", mono=True
    )
    return c


if __name__ == "__main__":
    print(build().save("fig5-lifecycle"))
