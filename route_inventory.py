"""Framework-version-neutral inspection of effective FastAPI routes.

FastAPI 0.141 keeps routers passed to ``include_router`` as nested route
entries.  Requests are resolved correctly, but a direct ``app.routes`` scan
then omits all child paths.  Diagnostics and contract tests use this module so
they report the public HTTP surface rather than a framework-specific tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator


@dataclass(frozen=True)
class EffectiveRoute:
    path: str
    methods: frozenset[str]
    source: Any


def _join_path(prefix: str, path: str) -> str:
    if not prefix:
        return path or ""
    if not path:
        return prefix
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def _iter_routes(
    routes: Iterable[Any],
    prefix: str = "",
) -> Iterator[EffectiveRoute]:
    for route in routes:
        included_router = getattr(route, "original_router", None)
        if included_router is not None:
            include_context = getattr(route, "include_context", None)
            include_prefix = str(
                getattr(include_context, "prefix", "") or ""
            )
            yield from _iter_routes(
                getattr(included_router, "routes", []) or [],
                _join_path(prefix, include_prefix),
            )
            continue

        path = str(getattr(route, "path", "") or "")
        methods = frozenset(
            str(method).upper()
            for method in (getattr(route, "methods", set()) or set())
        )
        if path:
            yield EffectiveRoute(
                path=_join_path(prefix, path),
                methods=methods,
                source=route,
            )


def iter_effective_routes(app_or_router: Any) -> Iterator[EffectiveRoute]:
    """Yield public routes, recursively expanding included routers."""

    yield from _iter_routes(getattr(app_or_router, "routes", []) or [])

