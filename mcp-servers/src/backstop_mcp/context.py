"""Shared state for the MCP servers.

Each server is its own process, and each builds the dataset and the policy index
once on first use. Generation takes about a tenth of a second and the result is a
few megabytes, so there is nothing to gain from sharing it across processes and
plenty to lose: a shared cache would be a shared mutable surface between processes
that are meant to be isolated from one another.

Nothing here reaches the network or a database. That is what lets the whole tool
plane run - and be tested, and be handed to MCP Inspector - on a laptop with
nothing started.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from backstop_domain.generator import DEFAULT_SEED, Dataset, GeneratorConfig, generate
from backstop_domain.policy import PolicyCorpus, load_corpus
from backstop_domain.retrieval import ClauseIndex
from backstop_domain.store import MemoryStore

#: Where the policy corpus lives. Overridable so a lab can point at its own.
POLICY_DIR_ENV = "BACKSTOP_POLICY_DIR"
SEED_ENV = "BACKSTOP_DATASET_SEED"


def _repository_root() -> Path:
    """Walk up until the marker file appears.

    Servers are launched from wherever a client happens to start them - an IDE,
    MCP Inspector, a test - so a path relative to the working directory is not
    dependable.
    """
    for candidate in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "seed-data").is_dir():
            return candidate
    raise RuntimeError("could not locate the repository root from the backstop_mcp package")


def policy_directory() -> Path:
    override = os.environ.get(POLICY_DIR_ENV)
    if override:
        return Path(override)
    return _repository_root() / "seed-data" / "policies"


def dataset_seed() -> int:
    raw = os.environ.get(SEED_ENV)
    return int(raw) if raw else DEFAULT_SEED


@lru_cache(maxsize=1)
def dataset() -> Dataset:
    return generate(GeneratorConfig(seed=dataset_seed()))


@lru_cache(maxsize=1)
def store() -> MemoryStore:
    return MemoryStore(dataset())


@lru_cache(maxsize=1)
def corpus() -> PolicyCorpus:
    return load_corpus(policy_directory())


@lru_cache(maxsize=1)
def clause_index() -> ClauseIndex:
    return ClauseIndex(corpus())


def reset() -> None:
    """Drop every cache. For tests that change the environment."""
    dataset.cache_clear()
    store.cache_clear()
    corpus.cache_clear()
    clause_index.cache_clear()


class NotFound(ToolError):
    """A requested record does not exist.

    Subclasses the SDK's :class:`ToolError` deliberately, and that choice is worth
    explaining. The MCP server treats an unexpected exception as a crash and
    withholds its text from the caller, which is the right default: an upstream
    stack trace is an information leak, and a model that reads one will try to
    work around it. ``ToolError`` is the opt-in for messages we have decided the
    caller should see.

    "No order with id ORD-9999999" is such a message. A tool that silently
    returned nothing would teach a model the order does not exist, when in fact
    the identifier may simply be wrong - and a model that believes an order does
    not exist will invent a reason why.
    """


__all__ = [
    "POLICY_DIR_ENV",
    "SEED_ENV",
    "NotFound",
    "clause_index",
    "corpus",
    "dataset",
    "dataset_seed",
    "policy_directory",
    "reset",
    "store",
]
