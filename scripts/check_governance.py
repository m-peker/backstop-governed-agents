"""Governance integrity checks.

Three properties that nothing else in the test suite would notice breaking,
because each of them fails silently rather than loudly.

**A prompt edited without a version bump.** The code still runs, the tests still
pass, and every decision dossier written before the edit now claims a prompt
version that no longer says what it said. The hash pinned in the lock file is
what catches it.

**A policy rule citing a clause that no longer exists.** The rule still fires and
the ruling still reads convincingly, right up until someone follows the citation.

**A planted ambiguity pointing at a renumbered clause.** The eval label quietly
stops testing anything, and the metric it feeds keeps reporting a number.

Run one check or all of them::

    uv run python scripts/check_governance.py prompts
    uv run python scripts/check_governance.py all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = REPOSITORY_ROOT / "seed-data" / "policies"
LOCK = REPOSITORY_ROOT / "governance" / "prompt-registry" / "prompts.lock.json"


def _clause_ids() -> set[str]:
    from backstop_domain.policy import load_corpus

    return {clause.id for clause in load_corpus(POLICY_DIR).clauses}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def check_prompts(*, write: bool = False) -> list[str]:
    """Compare every registered prompt against its pinned hash."""
    from backstop_graph import prompts

    registry = {prompt.reference: prompt.hash for prompt in prompts.registry()}

    if write or not LOCK.exists():
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  wrote {len(registry)} prompt hashes to {LOCK.relative_to(REPOSITORY_ROOT)}")
        return []

    pinned: dict[str, str] = json.loads(LOCK.read_text(encoding="utf-8"))
    problems: list[str] = []

    for reference, digest in registry.items():
        expected = pinned.get(reference)
        if expected is None:
            problems.append(
                f"{reference} is registered but not pinned. A new prompt version "
                f"needs a lock entry: run `check_governance.py prompts --write`."
            )
        elif expected != digest:
            problems.append(
                f"{reference} was edited without a version bump "
                f"(pinned {expected}, now {digest}). Bump the version so that "
                f"dossiers written under the old text still name the old version."
            )

    for reference in pinned:
        if reference not in registry:
            problems.append(f"{reference} is pinned but no longer registered.")

    if not problems:
        print(f"  {len(registry)} prompt(s) match their pinned hashes")
    return problems


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def check_rules() -> list[str]:
    """Every policy rule must name clauses, and they must exist."""
    from backstop_policy import ALL_RULES

    known = _clause_ids()
    problems: list[str] = []

    for rule in ALL_RULES:
        if not rule.clauses:
            problems.append(f"{rule.id} cites no clause at all")
        if not rule.description:
            problems.append(f"{rule.id} has no description")
        for clause in rule.clauses:
            if clause not in known:
                problems.append(f"{rule.id} cites {clause}, which is not in the corpus")

    ids = [rule.id for rule in ALL_RULES]
    for duplicate in {rule_id for rule_id in ids if ids.count(rule_id) > 1}:
        problems.append(f"duplicate rule id {duplicate}")

    if not problems:
        print(f"  {len(ALL_RULES)} rule(s) cite {len(known)} known clauses")
    return problems


# ---------------------------------------------------------------------------
# Ambiguities
# ---------------------------------------------------------------------------


def check_ambiguities() -> list[str]:
    """The planted contradictions must still point at real, conflicting clauses."""
    from backstop_domain.policy import ExpectedBehaviour, load_corpus

    corpus = load_corpus(POLICY_DIR)
    known = _clause_ids()
    problems: list[str] = []

    for ambiguity in corpus.ambiguities:
        for clause in ambiguity.clauses:
            if clause not in known:
                problems.append(f"{ambiguity.id} cites {clause}, which no longer exists")
        if len(ambiguity.clauses) < 2:
            problems.append(f"{ambiguity.id} names fewer than two clauses")
        if not ambiguity.must_not:
            problems.append(f"{ambiguity.id} records no plausible wrong answers")

    behaviours = {ambiguity.expected_behaviour for ambiguity in corpus.ambiguities}
    missing = set(ExpectedBehaviour) - behaviours
    if missing:
        problems.append("no ambiguity exercises: " + ", ".join(sorted(b.value for b in missing)))

    problems.extend(_check_deliberation_still_reachable())

    if not problems:
        print(f"  {len(corpus.ambiguities)} planted ambiguity/ambiguities intact")
    return problems


def _check_deliberation_still_reachable() -> list[str]:
    """At least one real case must still route to the deliberation room.

    The routing depends on rulings carrying ``ambiguous=True``. Drop that flag in
    a refactor and every hard case quietly goes to the approval queue unargued -
    the system still works, the tests still pass, and the deliberation room simply
    never convenes again. Nothing else would notice.

    So this asserts the property end to end, on the case AMB-01 describes.
    """
    from decimal import Decimal

    from backstop_policy import Intent, PolicyContext, PolicyEngine, Resolution

    # Damage reported twelve days after delivery: RP-4.2 sets a 48-hour deadline
    # and attaches no consequence, RP-4.1 grants the remedy unconditionally.
    decision = PolicyEngine().evaluate(
        PolicyContext(
            intent=Intent.DAMAGED_ON_ARRIVAL,
            resolution=Resolution.FULL_REFUND,
            amount=Decimal("40.00"),
            order_total=Decimal("60.00"),
            cited_clauses=("RP-4.1",),
            days_since_delivery=12,
        )
    )

    if not decision.needs_deliberation:
        return [
            "the AMB-01 case no longer routes to deliberation; check that rulings "
            "still carry ambiguous=True"
        ]
    return []


CHECKS = {
    "prompts": lambda: check_prompts(),
    "rules": check_rules,
    "ambiguities": check_ambiguities,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=[*CHECKS, "all"], nargs="?", default="all")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Re-pin prompt hashes. Use when deliberately publishing a new version.",
    )
    args = parser.parse_args(argv)

    if args.check == "prompts" and args.write:
        check_prompts(write=True)
        return 0

    selected = CHECKS if args.check == "all" else {args.check: CHECKS[args.check]}
    problems: list[str] = []

    for name, check in selected.items():
        print(f"{name}:")
        problems.extend(check())

    if problems:
        print("\nFAILED")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nPASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
