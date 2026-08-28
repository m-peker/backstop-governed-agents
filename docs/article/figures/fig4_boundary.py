"""Figure 4 - the ordered checks a call passes before anything moves.

The order is the design. The kill switch is first because a system being turned
off should not depend on the correctness of anything after it, and the approval
check is last because it is the only one that can be satisfied by a person.
"""

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
    RED_EDGE,
    RED_FILL,
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
    title,
)

W = 1200
H = 850

MX, MW = 40, 700  # the gate stack
PX, PW = 780, 380  # the side panels


def build() -> Canvas:
    c = Canvas(W, H)

    title(
        c,
        MX,
        46,
        "The five checks that stand between a proposal and a payment",
        "In this order, every time, whoever is asking and however convinced they are.",
    )

    # -- the call ----------------------------------------------------------
    y = 104
    c.box(MX, y, MW, 72, fill=VIOLET_FILL, stroke=VIOLET_EDGE, width=1.7, radius=10, dash="6 4")
    c.text(
        MX + 16, y + 25, "WHAT THE MODEL ASKS FOR", size=10.5, fill=VIOLET, bold=True, spacing=0.9
    )
    c.text(
        MX + 16, y + 50, "issue_refund(order=ORD-8821, amount=590.27)", size=13, fill=INK, mono=True
    )
    c.line(MX + MW / 2, y + 72, MX + MW / 2, y + 96, arrow="a")
    y += 96

    gates = [
        (
            "kill switch",
            "Is the whole tool plane halted?",
            "kill switch engaged - no tool runs",
        ),
        (
            "scope",
            "Does this caller hold payments:write?",
            "deliberation:customer_advocate does not hold payments:write",
        ),
        (
            "rate limit",
            "Is this caller inside its token bucket?",
            "rate limit exceeded for graph:execute",
        ),
        (
            "idempotency",
            "Has this exact call already run?",
            "replayed - the earlier result is returned, not a second payment",
        ),
        (
            "approval",
            "Is there a signed token for this exact call?",
            "590.27 exceeds the automatic approval ceiling of 75.00",
        ),
    ]

    row_h = 92
    for i, (name, check, refusal) in enumerate(gates):
        gy = y + i * (row_h + 12)
        last = i == len(gates) - 1
        c.box(MX, gy, MW, row_h, fill=TEAL_FILL, stroke=TEAL_EDGE, width=1.7, radius=10)
        c.box(MX + 16, gy + 16, 28, 28, fill=TEAL, stroke=TEAL, radius=14)
        c.text(MX + 30, gy + 26, str(i + 1), size=13, fill=PAGE, anchor="middle", bold=True)
        c.text(MX + 56, gy + 26, name, size=15, fill=TEAL, bold=True)
        c.text(MX + 56, gy + 46, check, size=12, fill=MUTED)

        c.box(MX + 16, gy + 58, MW - 32, 24, fill=PAGE, stroke=RED_EDGE, width=1.1, radius=5)
        c.text(MX + 26, gy + 74, "refuses:", size=10.5, fill=RED, bold=True)
        c.text(MX + 84, gy + 74, refusal, size=11, fill=RED, mono=True)

        if not last:
            c.line(
                MX + MW / 2,
                gy + row_h,
                MX + MW / 2,
                gy + row_h + 12,
                stroke=TEAL,
                width=1.6,
                arrow="a-teal",
            )

    y += 5 * (row_h + 12)

    # -- the two outcomes --------------------------------------------------
    c.line(MX + MW / 2, y - 12, MX + MW / 2, y + 14, stroke=TEAL, width=1.6, arrow="a-teal")
    y += 14
    half = (MW - 16) / 2
    c.box(MX, y, half, 92, fill=RED_FILL, stroke=RED_EDGE, width=1.7, radius=10)
    c.text(MX + 16, y + 26, "NO TOKEN", size=10.5, fill=RED, bold=True, spacing=0.9)
    for i, line in enumerate(
        [
            "Refused at check 5 and written to the",
            "audit chain. The model may be entirely",
            "convinced. Nothing moved.",
        ]
    ):
        c.text(MX + 16, y + 48 + i * 15, line, size=11.5, fill=INK)

    c.box(MX + half + 16, y, half, 92, fill=TEAL_FILL, stroke=TEAL, width=1.7, radius=10)
    c.text(
        MX + half + 32,
        y + 26,
        "TOKEN BOUND TO THIS CALL",
        size=10.5,
        fill=TEAL,
        bold=True,
        spacing=0.9,
    )
    for i, line in enumerate(
        [
            "Executed once. A retry after a crash",
            "returns the first result rather than",
            "issuing a second refund.",
        ]
    ):
        c.text(MX + half + 32, y + 48 + i * 15, line, size=11.5, fill=INK)

    # -- what the token binds ---------------------------------------------
    py = 104
    c.box(PX, py, PW, 250, fill=AMBER_FILL, stroke=AMBER_EDGE, width=1.7, radius=12)
    c.text(PX + 20, py + 28, "WHAT THE APPROVAL BINDS", size=11, fill=AMBER, bold=True, spacing=0.9)
    fields = [
        ("ticket_id", "TCK-0966599745"),
        ("tool", "issue_refund"),
        ("args_digest", "sha256(canonical args)"),
        ("max_amount", "590.27"),
        ("expires_at", "2026-08-28T09:14:00Z"),
    ]
    for i, (k, v) in enumerate(fields):
        c.text(PX + 20, py + 58 + i * 20, k, size=11.5, fill=SLATE, mono=True)
        c.text(PX + 140, py + 58 + i * 20, v, size=11.5, fill=MUTED, mono=True)
    c.line(PX + 20, py + 168, PX + PW - 20, py + 168, stroke=AMBER_EDGE, width=1)
    for i, line in enumerate(
        [
            "Signed with HMAC-SHA256. Approving",
            "75.00 does not authorise 590.27, and",
            "the graph cannot re-sign: the key is",
            "not on its side of the boundary.",
        ]
    ):
        c.text(PX + 20, py + 192 + i * 16, line, size=11.5, fill=INK)

    # -- the derived key ---------------------------------------------------
    py2 = py + 274
    c.box(PX, py2, PW, 174, fill=SLATE_FILL, stroke=SLATE_EDGE, width=1.7, radius=12)
    c.text(PX + 20, py2 + 28, "WHY A RETRY IS SAFE", size=11, fill=SLATE, bold=True, spacing=0.9)
    c.text(PX + 20, py2 + 56, "idempotency_key =", size=11.5, fill=SLATE, mono=True)
    c.text(PX + 36, py2 + 74, "sha256(ticket, tool, args)", size=11.5, fill=TEAL, mono=True)
    for i, line in enumerate(
        [
            "The key is derived from the call, not",
            "supplied with it, so a caller retrying",
            "after a timeout cannot opt out of it -",
            "by accident or on purpose.",
        ]
    ):
        c.text(PX + 20, py2 + 104 + i * 16, line, size=11.5, fill=INK)

    # -- the point ---------------------------------------------------------
    py3 = py2 + 198
    c.box(PX, py3, PW, 218, fill=PANEL, stroke=LINE, width=1.7, radius=12)
    c.text(PX + 20, py3 + 28, "THE POINT", size=11, fill=INK, bold=True, spacing=0.9)
    for i, line in enumerate(
        [
            "None of these five checks reads the",
            "customer's message. None of them can",
            "be argued with, flattered, or told",
            "about a new company policy.",
            "",
            "That is the whole reason the attack",
            "success rate is 0% and the detection",
            "rate is merely interesting: detection",
            "is a heuristic, and this is not.",
        ]
    ):
        if line:
            c.text(PX + 20, py3 + 56 + i * 17, line, size=11.5, fill=INK)

    c.text(
        W - 40, H - 24, "backstop-governed-agents", size=11.5, fill=FAINT, anchor="end", mono=True
    )
    return c


if __name__ == "__main__":
    print(build().save("fig4-boundary"))
