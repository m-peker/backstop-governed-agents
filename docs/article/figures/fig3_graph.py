"""Figure 3 - the resolution graph, and the edge that is deliberately absent.

The missing transition is shown as a badge rather than as a crossed-out arrow
in the graph itself: drawing an edge in order to say it is not there tangles
with the edges that are, and a reader should not have to work out which of two
overlapping arrows is the real one.
"""

from __future__ import annotations

from _theme import (
    AMBER,
    AMBER_FILL,
    FAINT,
    INK,
    MUTED,
    PAGE,
    PANEL,
    RED,
    RED_EDGE,
    RED_FILL,
    SLATE_EDGE,
    TEAL,
    TEAL_FILL,
    VIOLET,
    VIOLET_FILL,
    Canvas,
    title,
)

W = 1240
H = 1150

NW, NH = 200, 46
SX = 180  # spine
BX = 560  # branch
GUT_BLOCK = 108  # far-left rail: blocked
GUT_DENY = 146  # inner-left rail: denied


def node(
    c: Canvas,
    x: float,
    y: float,
    label: str,
    *,
    fill: str = PAGE,
    stroke: str = SLATE_EDGE,
    ink: str = INK,
    dash: str | None = None,
    sub: str | None = None,
    w: float = NW,
) -> None:
    c.box(x, y, w, NH, fill=fill, stroke=stroke, width=1.6, radius=9, dash=dash)
    if sub:
        c.text(x + w / 2, y + 20, label, size=13, anchor="middle", fill=ink, mono=True)
        c.text(x + w / 2, y + 35, sub, size=10.5, anchor="middle", fill=MUTED, italic=True)
    else:
        c.text(x + w / 2, y + NH / 2 + 4.5, label, size=13, anchor="middle", fill=ink, mono=True)


def build() -> Canvas:
    c = Canvas(W, H)

    title(
        c,
        40,
        46,
        "The resolution graph",
        "A typed state machine. A ticket can pause for days waiting on a person and resume where it stopped.",
    )

    spine = [
        ("guardrail_in", None),
        ("classify", None),
        ("gather_facts", "concurrent tool calls"),
        ("policy_retrieval", None),
        ("assess", "the model proposes"),
        ("policy_gate", "deterministic"),
    ]
    y0, step = 110, 68
    ys: dict[str, float] = {}
    for i, (name, sub) in enumerate(spine):
        y = y0 + i * step
        ys[name] = y
        gate = name == "policy_gate"
        model = name in {"classify", "assess"}
        node(
            c,
            SX,
            y,
            name,
            sub=sub,
            fill=TEAL_FILL if gate else (VIOLET_FILL if model else PAGE),
            stroke=TEAL if gate else (VIOLET if model else SLATE_EDGE),
            ink=TEAL if gate else (VIOLET if model else INK),
            dash="5 3" if model else None,
        )
        if i:
            c.line(SX + NW / 2, y - step + NH, SX + NW / 2, y, arrow="a")

    gate_y = ys["policy_gate"]
    gate_end = gate_y + NH

    delib_y = gate_end + 52
    human_y = delib_y + 100
    exec_y = human_y + 122
    reply_y = exec_y + 84
    out_y = reply_y + 68
    close_y = out_y + 68

    node(
        c,
        BX,
        delib_y,
        "deliberate",
        sub="AutoGen room",
        fill=VIOLET_FILL,
        stroke=VIOLET,
        ink=VIOLET,
        dash="5 3",
    )
    node(
        c,
        BX,
        human_y,
        "human_approval",
        sub="interrupt() - the graph stops here",
        fill=AMBER_FILL,
        stroke=AMBER,
        ink=AMBER,
        w=262,
    )
    node(
        c,
        SX,
        exec_y,
        "execute",
        sub="through the tool gateway",
        fill=TEAL_FILL,
        stroke=TEAL,
        ink=TEAL,
    )
    node(c, SX, reply_y, "compose_reply")
    node(c, SX, out_y, "guardrail_out")
    node(c, SX, close_y, "close", fill=PANEL)

    for a, b in ((exec_y, reply_y), (reply_y, out_y), (out_y, close_y)):
        c.line(SX + NW / 2, a + NH, SX + NW / 2, b, arrow="a")

    # policy_gate -> deliberate
    c.path(
        f"M {SX + NW} {gate_y + NH / 2} L {BX + 100} {gate_y + NH / 2} L {BX + 100} {delib_y}",
        stroke=VIOLET,
        width=1.5,
        arrow="a-violet",
    )
    c.text(SX + NW + 14, gate_y + NH / 2 - 9, "the policy contradicts itself", size=11, fill=VIOLET)

    # deliberate -> human_approval
    c.line(BX + 100, delib_y + NH, BX + 100, human_y, stroke=AMBER, width=1.5, arrow="a-amber")

    # policy_gate -> human_approval
    c.path(
        f"M {SX + NW - 44} {gate_end} L {SX + NW - 44} {human_y + NH / 2} L {BX} {human_y + NH / 2}",
        stroke=AMBER,
        width=1.5,
        arrow="a-amber",
    )
    c.text(SX + NW - 36, human_y + NH / 2 - 9, "a rule requires a person", size=11, fill=AMBER)

    # policy_gate -> execute
    c.path(f"M {SX + 52} {gate_end} L {SX + 52} {exec_y}", stroke=TEAL, width=1.7, arrow="a-teal")
    c.text(SX + 60, gate_end + 34, "permitted", size=11, fill=TEAL)

    # human_approval -> execute
    c.path(
        f"M {BX} {human_y + NH - 13} L {SX + NW + 62} {human_y + NH - 13} "
        f"L {SX + NW + 62} {exec_y + NH / 2} L {SX + NW} {exec_y + NH / 2}",
        stroke=AMBER,
        width=1.5,
        arrow="a-amber",
    )
    c.text(SX + NW + 70, exec_y + NH / 2 - 9, "approved", size=11, fill=AMBER)

    # human_approval -> compose_reply
    c.path(
        f"M {BX + 30} {human_y + NH} L {BX + 30} {reply_y + NH / 2} L {SX + NW} {reply_y + NH / 2}",
        stroke=RED,
        width=1.4,
        dash="5 4",
        arrow="a-red",
    )
    c.text(BX + 22, reply_y + NH / 2 - 9, "declined", size=11, fill=RED, anchor="end")

    # policy_gate -> compose_reply
    c.path(
        f"M {SX} {gate_y + NH / 2} L {GUT_DENY} {gate_y + NH / 2} L {GUT_DENY} {reply_y + 15} L {SX} {reply_y + 15}",
        stroke=RED,
        width=1.4,
        dash="5 4",
        arrow="a-red",
    )
    c.vtext(GUT_DENY - 9, (gate_y + reply_y) / 2, "denied", size=11, fill=RED)

    # guardrail_in -> close
    c.path(
        f"M {SX} {ys['guardrail_in'] + NH / 2} L {GUT_BLOCK} {ys['guardrail_in'] + NH / 2} "
        f"L {GUT_BLOCK} {close_y + NH / 2} L {SX} {close_y + NH / 2}",
        stroke=RED,
        width=1.4,
        dash="5 4",
        arrow="a-red",
    )
    c.vtext(
        GUT_BLOCK - 9,
        (ys["guardrail_in"] + close_y) / 2,
        "blocked - no model is called",
        size=11,
        fill=RED,
    )

    # -- the transition that is not in the graph ---------------------------
    px, py, pw, ph = 856, exec_y - 96, 344, 210
    c.box(px, py, pw, ph, fill=RED_FILL, stroke=RED_EDGE, width=1.7, radius=12)
    c.text(
        px + 20, py + 30, "THE EDGE THAT IS NOT THERE", size=11, fill=RED, bold=True, spacing=0.9
    )

    chip_y = py + 50
    for label, x, w in (("deliberate", px + 20, 116), ("execute", px + 208, 116)):
        c.box(x, chip_y, w, 30, fill=PAGE, stroke=RED_EDGE, width=1.3, radius=7)
        c.text(x + w / 2, chip_y + 20, label, size=11.5, anchor="middle", fill=MUTED, mono=True)
    c.line(px + 136, chip_y + 15, px + 190, chip_y + 15, stroke=RED, width=1.8, dash="3 4")
    cx, cy, r = px + 172, chip_y + 15, 14
    c.box(cx - r, cy - r, 2 * r, 2 * r, fill=PAGE, stroke=RED, width=2, radius=r)
    c.line(cx - 6.5, cy - 6.5, cx + 6.5, cy + 6.5, stroke=RED, width=2.3)
    c.line(cx + 6.5, cy - 6.5, cx - 6.5, cy + 6.5, stroke=RED, width=2.3)

    for i, line in enumerate(
        [
            "The room recommends; a person decides.",
            "",
            "Nothing the three agents agree on can reach",
            "a tool by itself, because there is no path in",
            "the graph that would let it. The guarantee is",
            "the absent edge - not a sentence in a prompt",
            "asking the agents politely not to.",
        ]
    ):
        if line:
            c.text(px + 20, py + 110 + i * 16, line, size=11.5, fill=INK)

    # -- legend ------------------------------------------------------------
    ly = H - 44
    for i, (colour, label, dashed) in enumerate(
        [
            (TEAL, "deterministic", False),
            (VIOLET, "the model", True),
            (AMBER, "a person", False),
            (RED, "a refusal", False),
        ]
    ):
        x = 40 + i * 172
        c.box(
            x,
            ly - 8,
            26,
            14,
            fill=PAGE,
            stroke=colour,
            width=2,
            radius=4,
            dash="4 3" if dashed else None,
        )
        c.text(x + 34, ly + 3.5, label, size=13, fill=MUTED)
    c.text(
        W - 40, ly + 3.5, "backstop-governed-agents", size=11.5, fill=FAINT, anchor="end", mono=True
    )

    return c


if __name__ == "__main__":
    print(build().save("fig3-graph"))
