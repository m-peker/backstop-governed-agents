"""Figure 6 - why editing the record is not quietly possible."""

from __future__ import annotations

from _theme import (
    FAINT,
    INK,
    MUTED,
    PAGE,
    RED,
    RED_EDGE,
    RED_FILL,
    SLATE,
    SLATE_EDGE,
    SLATE_FILL,
    TEAL,
    TEAL_EDGE,
    TEAL_FILL,
    Canvas,
    title,
)

W = 1200
H = 672

BW, BH = 244, 108
GAP = 44
X0 = 40


def block(
    c: Canvas,
    x: float,
    y: float,
    index: int,
    rows: list[tuple[str, str]],
    *,
    ok: bool,
    broken: bool = False,
    edited: bool = False,
) -> None:
    if edited:
        fill, edge, ink = RED_FILL, RED, RED
    elif broken:
        fill, edge, ink = PAGE, RED_EDGE, RED
    else:
        fill, edge, ink = TEAL_FILL, TEAL_EDGE, TEAL

    c.box(x, y, BW, BH, fill=fill, stroke=edge, width=1.8, radius=10)
    c.text(x + 14, y + 24, f"entry {index}", size=12.5, fill=ink, bold=True, mono=True)

    mark = "verified" if ok else ("hash mismatch" if edited else "chain broken")
    c.text(x + BW - 14, y + 24, mark, size=10.5, fill=TEAL if ok else RED, anchor="end", bold=True)
    c.line(x + 14, y + 34, x + BW - 14, y + 34, stroke=edge, width=1)

    for i, (k, v) in enumerate(rows):
        c.text(x + 14, y + 54 + i * 17, k, size=10.5, fill=MUTED, mono=True)
        c.text(x + 106, y + 54 + i * 17, v, size=10.5, fill=INK if not edited else RED, mono=True)


def chain(c: Canvas, y: float, heading: str, sub: str, *, tampered: bool) -> None:
    c.text(X0, y, heading, size=15, fill=INK, bold=True)
    c.text(X0 + 8 + 250, y, sub, size=12.5, fill=MUTED)

    by = y + 22
    entries = [
        (0, [("actor", "graph:execute"), ("tool", "get_order"), ("decision", "ok")]),
        (1, [("actor", "graph:execute"), ("tool", "issue_refund"), ("decision", "refused")]),
        (2, [("actor", "reviewer:ops"), ("tool", "issue_refund"), ("decision", "approved")]),
        (3, [("actor", "graph:execute"), ("tool", "issue_refund"), ("decision", "ok")]),
    ]
    for i, (index, rows) in enumerate(entries):
        x = X0 + i * (BW + GAP)
        edited = tampered and index == 1
        broken = tampered and index >= 1
        if edited:
            rows = [
                ("actor", "graph:execute"),
                ("tool", "issue_refund"),
                ("decision", "ok  <- edited"),
            ]
        block(c, x, by, index, rows, ok=not broken, broken=broken, edited=edited)

        if i:
            lx = x - GAP
            severed = tampered and index >= 2
            colour = RED if severed else TEAL
            c.line(
                lx + 2,
                by + BH / 2,
                x - 4,
                by + BH / 2,
                stroke=colour,
                width=1.6,
                arrow="a-red" if severed else "a-teal",
            )
            c.text(
                lx + GAP / 2,
                by + BH / 2 - 10,
                "prev",
                size=9.5,
                fill=colour,
                anchor="middle",
                mono=True,
            )
            if severed:
                mx = lx + GAP / 2
                c.line(mx - 6, by + BH / 2 + 8, mx + 6, by + BH / 2 + 20, stroke=RED, width=2)
                c.line(mx + 6, by + BH / 2 + 8, mx - 6, by + BH / 2 + 20, stroke=RED, width=2)


def build() -> Canvas:
    c = Canvas(W, H)

    title(
        c,
        X0,
        46,
        "An audit trail that notices when it is edited",
        "Each entry hashes the one before it, so a change to any entry invalidates every entry after it.",
    )

    c.box(X0, 92, W - 80, 46, fill=SLATE_FILL, stroke=SLATE_EDGE, width=1.5, radius=8)
    c.text(
        X0 + 16,
        121,
        "entry_hash = sha256(prev_hash + canonical_json(payload))",
        size=13,
        fill=SLATE,
        mono=True,
    )
    c.text(
        W - 56,
        121,
        "arguments are stored as a digest, never in the clear",
        size=11.5,
        fill=MUTED,
        anchor="end",
    )

    chain(
        c,
        168,
        "As written",
        "the verifier walks the chain and recomputes every hash",
        tampered=False,
    )
    chain(
        c,
        368,
        "After someone edits entry 1",
        "to make a refusal look like an approval",
        tampered=True,
    )

    fy = 566
    c.box(X0, fy, W - 80, 74, fill=RED_FILL, stroke=RED_EDGE, width=1.6, radius=10)
    c.text(X0 + 18, fy + 26, "WHAT THE VERIFIER SAYS", size=10.5, fill=RED, bold=True, spacing=0.9)
    c.text(X0 + 18, fy + 50, "entry 1 has been modified", size=12.5, fill=RED, mono=True)
    c.text(
        X0 + 300,
        fy + 50,
        "Rewriting one entry means rewriting all of them - and the hash of the last entry is the thing you publish.",
        size=12,
        fill=INK,
    )

    c.text(
        W - 40, H - 16, "backstop-governed-agents", size=11.5, fill=FAINT, anchor="end", mono=True
    )
    return c


if __name__ == "__main__":
    print(build().save("fig6-audit"))
