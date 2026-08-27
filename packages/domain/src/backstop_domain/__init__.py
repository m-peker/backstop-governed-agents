"""Retail domain model, synthetic dataset and policy corpus.

This package holds no agent logic and no I/O beyond reading its own data files.
Everything above it - the MCP servers, the graph, the evaluation harness - depends
on these types, so keeping the package dependency-light keeps the whole tree
testable without a database or a model provider.
"""

from backstop_domain.fraud import FraudAnnotation, FraudPattern
from backstop_domain.generator import Dataset, GeneratorConfig, generate
from backstop_domain.money import Money, money

__all__ = [
    "Dataset",
    "FraudAnnotation",
    "FraudPattern",
    "GeneratorConfig",
    "Money",
    "generate",
    "money",
]
