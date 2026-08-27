"""Acceptance check for lab 04.

Five properties. Each one is something the naive gateway does not do, and each
maps to one of the TODOs in ``start_here.py``.
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append((name, passed, detail))


async def main() -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from start_here import CEILING, NaiveGateway, PaymentsLedger

    from backstop_toolgateway.errors import ApprovalRequired, ScopeDenied
    from backstop_toolgateway.principal import GRAPH_EXECUTOR, GRAPH_INVESTIGATOR
    from backstop_toolgateway.scopes import DEFAULT_REGISTRY

    args = {"order_id": "ORD-0000028", "amount_eur": "40.00", "reason": "damaged"}

    # 1 - scope ------------------------------------------------------------
    gateway = NaiveGateway(DEFAULT_REGISTRY, PaymentsLedger())
    try:
        await gateway.invoke(
            principal=GRAPH_INVESTIGATOR, ticket_id="T1", tool="issue_refund", args=args
        )
        record("a read-only principal cannot move money", False, "the call went through")
    except ScopeDenied:
        record("a read-only principal cannot move money", True)
    except Exception as exc:  # noqa: BLE001 - a lab is allowed to be wrong
        record("a read-only principal cannot move money", False, f"raised {type(exc).__name__}")

    # 2 - idempotency ------------------------------------------------------
    ledger = PaymentsLedger()
    gateway = NaiveGateway(DEFAULT_REGISTRY, ledger)
    try:
        await gateway.invoke(
            principal=GRAPH_EXECUTOR, ticket_id="T2", tool="issue_refund", args=args
        )
        await gateway.invoke(
            principal=GRAPH_EXECUTOR, ticket_id="T2", tool="issue_refund", args=args
        )
    except Exception as exc:  # noqa: BLE001
        record("a replayed call refunds once", False, f"raised {type(exc).__name__}")
    else:
        record(
            "a replayed call refunds once",
            len(ledger.movements) == 1,
            f"{len(ledger.movements)} movement(s)",
        )

        # 3 - a genuinely different call is not swallowed -------------------
        try:
            await gateway.invoke(
                principal=GRAPH_EXECUTOR,
                ticket_id="T2",
                tool="issue_refund",
                args={**args, "order_id": "ORD-0000029"},
            )
        except Exception as exc:  # noqa: BLE001
            record("a different call is not a duplicate", False, f"raised {type(exc).__name__}")
        else:
            record(
                "a different call is not a duplicate",
                len(ledger.movements) == 2,
                f"{len(ledger.movements)} movement(s)",
            )

    # 4 - approval ---------------------------------------------------------
    ledger = PaymentsLedger()
    gateway = NaiveGateway(DEFAULT_REGISTRY, ledger)
    large = {**args, "amount_eur": str(CEILING + Decimal("1"))}
    try:
        await gateway.invoke(
            principal=GRAPH_EXECUTOR, ticket_id="T3", tool="issue_refund", args=large
        )
        record("an amount over the ceiling needs approval", False, "the call went through")
    except ApprovalRequired:
        record("an amount over the ceiling needs approval", True)
    except Exception as exc:  # noqa: BLE001
        record("an amount over the ceiling needs approval", False, f"raised {type(exc).__name__}")

    # 5 - audit ------------------------------------------------------------
    chain = getattr(gateway, "audit", None)
    record(
        "every attempt is recorded, refusals included",
        chain is not None and len(chain) > 0,
        "no `audit` chain on the gateway" if chain is None else "",
    )

    print()
    for name, passed, detail in RESULTS:
        mark = "PASS" if passed else "FAIL"
        suffix = f"  ({detail})" if detail else ""
        print(f"  [{mark}]  {name}{suffix}")

    failed = sum(1 for _, passed, _ in RESULTS if not passed)
    print()
    if failed:
        print(f"{failed} of {len(RESULTS)} checks failing. Keep going.")
        return 1

    print("All checks passing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
