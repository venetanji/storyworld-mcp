"""Schemaless character model.

We intentionally avoid strict validation here because character YAMLs
in this project may be heterogeneous. Export a `Character` type alias
that other modules can import and treat as a plain mapping.
"""
from typing import Any, Dict

# Character is a schemaless mapping of keys to values parsed from YAML
Character = Dict[str, Any]
