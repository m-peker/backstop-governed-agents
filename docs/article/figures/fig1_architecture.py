"""Figure 1 - the planes a request crosses, and which of them can be persuaded.

Layout note: the audit panel sits on the left and the two bypass routes (an
input that never reaches a model, and a refusal that never reaches a tool) run
down the right. Keeping them on opposite sides means no connector crosses
another, which matters more here than symmetry.
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
    legend,
    text_width,
    title,
)

W = 1100
H = 1230

AX, AW = 40, 230  # the record, on the left
MX, MW = 380, 620  # the flow
MID = MX + MW / 2
LOOP = 350  # left gutter: the deliberation loop back
BYPASS_A = 1022  # right gutter: blocked at the door
BYPASS_B = 1058  # right gutter: refused by policy


def band(
    c: Canvas,
    y: float,
    h: float,
    heading: str,
    qualifier: str | None = None,
    *,
    accent: str,
    fill: str,
    edge: str,
    dash: str | None = None,
) -> None:
    c.box(MX, y, MW, h, fill=fill, stroke=edge, width=1.8, dash=dash, radius=12)
    c.text(MX + 16, y + 23, heading.upper(), size=11, fill=accent, bold=True, spacing=0.9)
    if qualifier:
        # Drawn as its own run: consecutive spaces collapse in SVG text.
        offset = MX + 16 + text_width(heading.upper(), 11, bold=True) + len(heading) * 0.9 + 20
        c.text(offset, y + 23, "/", size=11, fill=edge, bold=True)
        c.text(offset + 12, y + 23, qualifier, size=11, fill=MUTED, spacing=0.5)


def chips(
    c: Canvas,
    y: float,
    labels: list[str],
    *,
    ink: str,
    edge: str,
    h: float = 34,
    size: float = 12.5,
    gap: float = 12,
) -> None:
    n = len(labels)
    w = (MW - 32 - gap * (n - 1)) / n
    for i, label in enumerate(labels):
        x = MX + 16 + i * (w + gap)
        c.box(x, y, w, h, fill=PAGE, stroke=edge, width=1.3, radius=7)
        c.text(x + w / 2, y + h / 2 + size * 0.35, label, size=size, anchor="middle", fill=ink)
        if i < n - 1:
            c.line(x + w + 1.5, y + h / 2, x + w + gap - 2.5, y + h / 2, stroke=edge, width=1.2)


def build() -> Canvas:
    c = Canvas(W, H)

    title(
        c,
        AX,
        46,
        "Where a refund actually gets decided",
        "Solid teal is deterministic code. Dashed violet is the part that can be persuaded.",
    )

    # -- the message -------------------------------------------------------
    msg_y = 108
    c.label_box(
        MX + 140,
        msg_y,
        MW - 280,
        50,
        [
            ("Customer message", {"size": 14.5, "bold": True}),
            ("untrusted, always", {"size": 12, "fill": MUTED, "italic": True}),
        ],
        fill=PANEL,
        stroke=LINE,
        leading=16,
    )
    c.line(MID, msg_y + 50, MID, msg_y + 78, arrow="a")

    # -- input guardrails --------------------------------------------------
    in_y = 186
    band(c, in_y, 96, "Input guardrails", accent=TEAL, fill=TEAL_FILL, edge=TEAL_EDGE)
    chips(
        c,
        in_y + 40,
        ["normalise", "tokenise PII", "detect injection", "spotlight"],
        ink=TEAL,
        edge=TEAL_EDGE,
    )
    c.line(MID, in_y + 96, MID, in_y + 124, arrow="a")

    # -- orchestration -----------------------------------------------------
    orch_y = 310
    band(
        c,
        orch_y,
        112,
        "Orchestration",
        "the model proposes",
        accent=VIOLET,
        fill=VIOLET_FILL,
        edge=VIOLET_EDGE,
        dash="6 4",
    )
    half = (MW - 32 - 14) / 2
    for i, (name, l2, l3) in enumerate(
        [
            ("LangGraph", "typed resolution graph", "checkpointed, resumable"),
            ("AutoGen", "deliberation room", "analyst, advocate, investigator"),
        ]
    ):
        c.label_box(
            MX + 16 + i * (half + 14),
            orch_y + 34,
            half,
            62,
            [
                (name, {"size": 14, "bold": True, "fill": VIOLET}),
                (l2, {"size": 11.5, "fill": MUTED}),
                (l3, {"size": 11.5, "fill": MUTED}),
            ],
            fill=PAGE,
            stroke=VIOLET_EDGE,
            dash="5 3",
            leading=15,
        )
    c.line(MID, orch_y + 112, MID, orch_y + 140, arrow="a")

    # -- policy engine -----------------------------------------------------
    pol_y = 450
    pol_h = 116
    band(
        c,
        pol_y,
        pol_h,
        "Policy engine",
        "deterministic code disposes",
        accent=TEAL,
        fill=TEAL_FILL,
        edge=TEAL_EDGE,
    )
    c.text(
        MID,
        pol_y + 50,
        "18 versioned rules, each citing the clauses it implements",
        size=13,
        anchor="middle",
        fill=INK,
    )
    permit_x = MX + 116
    deny_x = MX + MW - 116
    for cx, label, colour, bg in (
        (permit_x, "PERMIT", TEAL, TEAL_FILL),
        (MID, "REQUIRE_HUMAN", AMBER, AMBER_FILL),
        (deny_x, "DENY", RED, RED_FILL),
    ):
        c.pill(
            cx, pol_y + 64, label, size=12, fill=bg, stroke=colour, ink=colour, bold=True, mono=True
        )
    pol_end = pol_y + pol_h

    # -- the deliberation loop, back up into the room ----------------------
    c.path(
        f"M {MX} {pol_y + 62} L {LOOP} {pol_y + 62} L {LOOP} {orch_y + 60} L {MX} {orch_y + 60}",
        stroke=VIOLET,
        width=1.5,
        dash="5 4",
        arrow="a-violet",
    )
    for i, part in enumerate(["the policy", "contradicts", "itself"]):
        c.text(LOOP - 8, pol_y + 6 + i * 14, part, size=10.5, fill=VIOLET, anchor="end")

    # -- branch region -----------------------------------------------------
    queue_y = pol_end + 40
    junction = pol_end + 112
    queue_x = MX + MW - 292

    c.path(
        f"M {MID} {pol_end} L {MID} {pol_end + 18} L {queue_x + 120} {pol_end + 18} "
        f"L {queue_x + 120} {queue_y}",
        stroke=AMBER,
        width=1.5,
        arrow="a-amber",
    )
    c.label_box(
        queue_x,
        queue_y,
        240,
        54,
        [
            ("Approval queue", {"size": 13.5, "bold": True, "fill": AMBER}),
            ("both sides already argued", {"size": 11.5, "fill": MUTED, "italic": True}),
        ],
        fill=AMBER_FILL,
        stroke=AMBER_EDGE,
        leading=16,
    )
    c.path(
        f"M {queue_x + 120} {queue_y + 54} L {queue_x + 120} {junction} L {permit_x} {junction}",
        stroke=AMBER,
        width=1.5,
    )
    c.text(
        queue_x + 108,
        junction - 10,
        "approved - the token is bound to this exact call",
        size=11,
        fill=AMBER,
        anchor="end",
    )
    c.line(permit_x, pol_end, permit_x, junction, stroke=TEAL, width=1.6)
    c.text(permit_x + 10, pol_end + 30, "permitted", size=11.5, fill=TEAL)

    cap_y = pol_end + 150
    c.line(permit_x, junction, permit_x, cap_y, stroke=TEAL, width=1.6, arrow="a-teal")

    # -- capability boundary ----------------------------------------------
    band(
        c,
        cap_y,
        96,
        "Capability boundary",
        "lives outside the model",
        accent=TEAL,
        fill=TEAL_FILL,
        edge=TEAL_EDGE,
    )
    chips(
        c,
        cap_y + 40,
        ["kill switch", "scope", "rate limit", "idempotency", "approval"],
        ink=TEAL,
        edge=TEAL_EDGE,
        size=11.5,
        gap=9,
    )
    c.line(MID, cap_y + 96, MID, cap_y + 124, arrow="a")

    # -- tool plane --------------------------------------------------------
    tool_y = cap_y + 124
    band(c, tool_y, 92, "MCP tool plane", accent=SLATE, fill=SLATE_FILL, edge=SLATE_EDGE)
    labels = ["orders", "shipping", "catalog", "policy RAG", "payments"]
    w = (MW - 32 - 9 * 4) / 5
    for i, label in enumerate(labels):
        x = MX + 16 + i * (w + 9)
        write = label == "payments"
        c.box(
            x,
            tool_y + 34,
            w,
            40,
            fill=RED_FILL if write else PAGE,
            stroke=RED if write else SLATE_EDGE,
            width=1.6 if write else 1.3,
            radius=7,
        )
        c.text(
            x + w / 2,
            tool_y + 34 + (18 if write else 24),
            label,
            size=11.5,
            anchor="middle",
            fill=RED if write else SLATE,
            bold=write,
        )
        if write:
            c.text(
                x + w / 2,
                tool_y + 34 + 32,
                "write",
                size=10,
                anchor="middle",
                fill=RED,
                italic=True,
            )
    c.line(MID, tool_y + 92, MID, tool_y + 120, arrow="a")

    # -- output guardrails -------------------------------------------------
    out_y = tool_y + 120
    band(c, out_y, 96, "Output guardrails", accent=TEAL, fill=TEAL_FILL, edge=TEAL_EDGE)
    chips(
        c,
        out_y + 40,
        ["schema", "groundedness", "policy re-check", "leak scan"],
        ink=TEAL,
        edge=TEAL_EDGE,
    )
    c.line(MID, out_y + 96, MID, out_y + 124, arrow="a")

    c.label_box(
        MX + 170,
        out_y + 124,
        MW - 340,
        44,
        [("Reply to the customer", {"size": 14, "bold": True})],
        fill=PANEL,
        stroke=LINE,
    )

    # -- the two bypasses, down the right ----------------------------------
    c.path(
        f"M {MX + MW} {in_y + 57} L {BYPASS_B} {in_y + 57} L {BYPASS_B} {out_y + 30} L {MX + MW} {out_y + 30}",
        stroke=RED,
        width=1.4,
        dash="5 4",
        arrow="a-red",
    )
    c.vtext(
        BYPASS_B - 9,
        (in_y + 57 + out_y + 30) / 2,
        "blocked - no model sees it",
        size=10.5,
        fill=RED,
    )

    c.path(
        f"M {deny_x} {pol_end} L {deny_x} {pol_end + 18} L {BYPASS_A} {pol_end + 18} "
        f"L {BYPASS_A} {out_y + 62} L {MX + MW} {out_y + 62}",
        stroke=RED,
        width=1.4,
        dash="5 4",
        arrow="a-red",
    )
    c.vtext(
        BYPASS_A - 9,
        (pol_end + 18 + out_y + 62) / 2,
        "denied - no tool is called",
        size=10.5,
        fill=RED,
    )

    # -- the record --------------------------------------------------------
    top, bottom = in_y, out_y + 96
    c.box(AX, top, AW, bottom - top, fill=SLATE_FILL, stroke=SLATE_EDGE, width=1.6, radius=12)
    c.text(AX + 16, top + 26, "HASH-CHAINED AUDIT", size=11, fill=SLATE, bold=True, spacing=0.9)

    notes = [
        ("Every decision is appended", 0),
        ("before the next one is taken.", 0),
        ("", 0),
        ("entry_hash = sha256(", 1),
        ("    prev_hash + payload)", 1),
        ("", 0),
        ("Arguments are stored as a", 0),
        ("digest, never in the clear,", 0),
        ("so the record can be kept", 0),
        ("longer than the data may be.", 0),
        ("", 0),
        ("A refusal is recorded as", 0),
        ("carefully as a success. The", 0),
        ("interesting question after", 0),
        ("an incident is usually what", 0),
        ("did not happen.", 0),
    ]
    ny = top + 56
    for note, mono in notes:
        if note:
            c.text(
                AX + 16,
                ny,
                note,
                size=11 if mono else 11.5,
                fill=SLATE if mono else MUTED,
                mono=bool(mono),
            )
        ny += 17

    entry_y = bottom - 176
    c.line(AX + 16, entry_y - 22, AX + AW - 16, entry_y - 22, stroke=SLATE_EDGE, width=1)
    c.text(AX + 16, entry_y - 2, "ONE ENTRY", size=10, fill=SLATE, bold=True, spacing=0.9)
    for i, field_name in enumerate(
        [
            "ticket_id",
            "actor",
            "tool",
            "args_digest",
            "decision",
            "reason",
            "prev_hash",
            "entry_hash",
        ]
    ):
        col, row = divmod(i, 4)
        c.text(
            AX + 16 + col * 104,
            entry_y + 20 + row * 17,
            field_name,
            size=10.5,
            fill=MUTED,
            mono=True,
        )

    for src_y in (in_y + 57, orch_y + 56, pol_y + 96, cap_y + 57, out_y + 57):
        c.line(
            MX - 6, src_y, AX + AW + 6, src_y, stroke=FAINT, width=1.1, dash="3 4", arrow="a-faint"
        )

    # -- legend ------------------------------------------------------------
    legend(
        c,
        AX,
        H - 40,
        [
            (TEAL, "deterministic", False),
            (VIOLET, "can be persuaded", True),
            (AMBER, "a person", False),
            (RED, "a refusal", False),
        ],
    )
    c.text(
        W - 40, H - 36, "backstop-governed-agents", size=11.5, fill=FAINT, anchor="end", mono=True
    )

    return c


if __name__ == "__main__":
    print(build().save("fig1-architecture"))
