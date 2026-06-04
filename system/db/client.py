from __future__ import annotations

import os
from typing import Any, Optional

from supabase import Client, create_client


_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


def insert(table: str, data: dict[str, Any]) -> dict[str, Any]:
    client = get_client()
    result = client.table(table).insert(data).execute()
    return result.data[0] if result.data else {}


def update(table: str, filters: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    client = get_client()
    query = client.table(table).update(data)
    for column, value in filters.items():
        query = query.eq(column, value)
    result = query.execute()
    return result.data


def select(
    table: str,
    filters: Optional[dict[str, Any]] = None,
    columns: str = "*",
    limit: Optional[int] = None,
    order_by: Optional[str] = None,
    order_desc: bool = False,
) -> list[dict[str, Any]]:
    client = get_client()
    query = client.table(table).select(columns)
    if filters:
        for column, value in filters.items():
            query = query.eq(column, value)
    if order_by:
        query = query.order(order_by, desc=order_desc)
    if limit:
        query = query.limit(limit)
    result = query.execute()
    return result.data


def upsert(table: str, data: dict[str, Any], on_conflict: Optional[str] = None) -> dict[str, Any]:
    client = get_client()
    kwargs: dict[str, Any] = {}
    if on_conflict:
        kwargs["on_conflict"] = on_conflict
    result = client.table(table).upsert(data, **kwargs).execute()
    return result.data[0] if result.data else {}


def select_raw(
    table: str,
    filters: Optional[dict[str, Any]] = None,
    columns: str = "*",
    limit: Optional[int] = None,
    order_by: Optional[str] = None,
    order_desc: bool = False,
    gte: Optional[dict[str, Any]] = None,
    lte: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    client = get_client()
    query = client.table(table).select(columns)
    if filters:
        for column, value in filters.items():
            query = query.eq(column, value)
    if gte:
        for column, value in gte.items():
            query = query.gte(column, value)
    if lte:
        for column, value in lte.items():
            query = query.lte(column, value)
    if order_by:
        query = query.order(order_by, desc=order_desc)
    if limit:
        query = query.limit(limit)
    result = query.execute()
    return result.data
