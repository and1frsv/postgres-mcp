"""Tests for exposing COMMENT ON metadata through introspection tools.

Table and column comments are the cheapest form of schema documentation a database
carries, and they are what tells an agent that `hits_view_search` means "impressions
in search" while `hits_view` is a grand total. Both introspection tools must surface
them, and the restricted access mode must permit the functions that read them.
"""

from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from postgres_mcp.server import get_object_details
from postgres_mcp.server import list_objects
from postgres_mcp.sql import SafeSqlDriver
from postgres_mcp.sql import SqlDriver


def _row(**cells):
    row = Mock()
    row.cells = cells
    return row


@pytest.mark.asyncio
async def test_comment_functions_allowed_in_restricted_mode():
    """obj_description/col_description must survive SafeSqlDriver validation."""
    inner = Mock(spec=SqlDriver)
    inner.execute_query = AsyncMock(return_value=[])
    safe = SafeSqlDriver(inner)

    await safe.execute_query(
        "SELECT obj_description(c.oid, 'pg_class'), col_description(c.oid, 1) FROM pg_class c"
    )

    inner.execute_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_objects_exposes_table_comment():
    """Listing tables returns the table comment alongside the name."""
    rows = [
        _row(
            table_schema="silver",
            table_name="ozon_analytics",
            table_type="BASE TABLE",
            object_comment="Analytics per SKU and day. Source: POST /v1/analytics/data",
        )
    ]

    with (
        patch("postgres_mcp.server.get_sql_driver", AsyncMock()),
        patch.object(SafeSqlDriver, "execute_param_query", AsyncMock(return_value=rows)),
    ):
        response = await list_objects(schema_name="silver", object_type="table")

    text = response[0].text
    assert "Source: POST /v1/analytics/data" in text


@pytest.mark.asyncio
async def test_get_object_details_exposes_table_and_column_comments():
    """Object details carry the table comment and a comment per column."""
    columns = [
        _row(
            column_name="hits_view_search",
            data_type="numeric",
            is_nullable="YES",
            column_default=None,
            column_comment="Impressions in search and category",
        )
    ]
    table_comment = [_row(object_comment="Analytics per SKU and day")]

    async def fake_param_query(_driver, query, _params=None):
        if "information_schema.columns" in query:
            return columns
        if "obj_description" in query:
            return table_comment
        return []

    with (
        patch("postgres_mcp.server.get_sql_driver", AsyncMock()),
        patch.object(SafeSqlDriver, "execute_param_query", AsyncMock(side_effect=fake_param_query)),
    ):
        response = await get_object_details(
            schema_name="silver", object_name="ozon_analytics", object_type="table"
        )

    text = response[0].text
    assert "Impressions in search and category" in text
    assert "Analytics per SKU and day" in text
