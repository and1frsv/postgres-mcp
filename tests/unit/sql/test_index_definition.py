"""IndexDefinition: the generated CREATE INDEX must be valid SQL for any table the tools accept.

The index name is derived from the table and column names; a schema-qualified table
("silver.orders") or a quoted column ('"Артикул"') used to leak '.' and '"' into the
unquoted name and turned every hypothetical index on a non-public table into a syntax error.
"""

import pytest
from pglast import parse_sql

from postgres_mcp.sql.index import IndexDefinition


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("silver.ozon_fbo_orders", ("city",)),
        ("gold.ozon_view_cluster_stocks", ('"Артикул"', '"Кластер"')),
        ('"Silver"."Orders"', ("lower(city)",)),
    ],
)
def test_definition_is_valid_sql_for_schema_qualified_and_quoted_names(table: str, columns: tuple[str, ...]) -> None:
    idx = IndexDefinition(table=table, columns=columns)
    parse_sql(idx.definition)  # raises ParseError on an invalid statement
    assert "." not in idx.name and '"' not in idx.name
    assert f" ON {table} USING " in idx.definition  # the table reference itself is kept as given


def test_plain_names_are_unchanged() -> None:
    idx = IndexDefinition(table="users", columns=("name", "email"))
    assert idx.definition == "CREATE INDEX crystaldba_idx_users_name_email_2 ON users USING btree (name, email)"
