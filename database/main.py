"""Connection pool, transaction helper, and ``ExtractTransformLoad`` base.

Every ETL in :mod:`database.etls` inherits from :class:`ExtractTransformLoad`
and goes through :func:`transaction` for its writes. The pool itself is a
lazy process-wide singleton: built on first use, closed at interpreter
shutdown via :func:`atexit`.
"""

from __future__ import annotations

import atexit
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from typing import Any, Iterator, Literal, LiteralString

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from functions.environment import get_environmental_variables

_POOL_MIN_SIZE = 1
_POOL_MAX_SIZE = 10

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    """Return the process-wide pool, creating it on first call."""
    global _pool
    if _pool is None:
        cfg = get_environmental_variables().database
        _pool = ConnectionPool(
            min_size=_POOL_MIN_SIZE,
            max_size=_POOL_MAX_SIZE,
            kwargs={
                "host": cfg.host,
                "port": cfg.port,
                "user": cfg.username,
                "password": cfg.password,
                "dbname": cfg.name,
            },
            open=True,
        )
        atexit.register(_close_pool)
    return _pool


def _close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """Yield a pooled connection inside a transaction.

    Commits on clean exit, rolls back on exception, and returns the
    connection to the pool either way. ``psycopg_pool.ConnectionPool``'s
    own ``connection()`` already provides this contract; this wrapper exists
    so callers depend on a stable name in our codebase rather than on the
    pool object directly.
    """
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn


class ExtractTransformLoad:
    """Base class for table-scoped ETLs.

    Subclasses get two parameterized-SQL primitives — :meth:`_execute` for
    single statements and :meth:`_executemany` for batch writes — and layer
    typed, table-specific methods on top. No ORM, no query builder: every
    statement in a subclass is hand-written SQL with ``%s`` placeholders.
    """

    def _execute(
        self,
        sql: LiteralString,
        params: Sequence[Any] | None = None,
        *,
        fetch: Literal["one", "all", "none"] = "none",
    ) -> Any:
        """Run ``sql`` in a transaction and optionally return rows.

        ``fetch="one"`` returns a single dict (or ``None``), ``fetch="all"``
        returns a list of dicts, ``fetch="none"`` returns ``None``.
        """
        with transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
                return None

    def _executemany(self, sql: LiteralString, rows: Iterable[Sequence[Any]]) -> int:
        """Run ``sql`` once per row tuple. Returns the affected row count."""
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
                return cur.rowcount
