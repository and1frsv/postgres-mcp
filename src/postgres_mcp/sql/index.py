import re
from dataclasses import dataclass
from typing import Any


def _name_part(text: str) -> str:
    """Reduce a table/column reference to a fragment usable inside an unquoted identifier."""
    return re.sub(r"\W+", "_", text).rstrip("_")


@dataclass(frozen=True)
class IndexDefinition:
    """Immutable index configuration for hashing."""

    table: str
    columns: tuple[str, ...]
    using: str = "btree"

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "columns": list(self.columns),
            "using": self.using,
            "definition": self.definition,
        }

    @property
    def definition(self) -> str:
        return f"CREATE INDEX {self.name} ON {self.table} USING {self.using} ({', '.join(self.columns)})"

    @property
    def name(self) -> str:
        # The name is an unquoted identifier, so every part must be reduced to letters,
        # digits and underscores: expressions like LOWER(column_name), schema-qualified
        # tables ("silver.orders") and quoted names ('"Артикул"') would otherwise leak
        # '(', '.', '"' into it and make the whole CREATE INDEX a syntax error.
        column_part = "_".join(_name_part(col) for col in self.columns)
        suffix = "" if self.using == "btree" else f"_{self.using}"
        base = f"crystaldba_idx_{_name_part(self.table)}_{column_part}_{len(self.columns)}"
        return f"{base}{suffix}"

    def __str__(self) -> str:
        return self.definition

    def __repr__(self) -> str:
        return f"IndexConfig(table='{self.table}', columns={self.columns}, using='{self.using}')"
