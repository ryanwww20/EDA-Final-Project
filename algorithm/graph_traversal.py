"""
Generic iterative graph traversal utilities.

These are domain-agnostic: callers supply a neighbor function (and optional
expand predicate) to adapt BFS/DFS to netlists, logic cones, path search, etc.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")

NeighborsFn = Callable[[T], Iterable[T]]
ShouldExpandFn = Callable[[T], bool]


def dfs(
    starts: Iterable[T],
    neighbors: NeighborsFn[T],
    *,
    should_expand: ShouldExpandFn[T] | None = None,
) -> list[T]:
    """Iterative depth-first traversal; each node visited at most once."""
    if should_expand is None:
        should_expand = lambda _node: True

    visited: set[T] = set()
    order: list[T] = []
    stack: list[T] = list(starts)

    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        order.append(node)

        if not should_expand(node):
            continue

        for nb in neighbors(node):
            if nb not in visited:
                stack.append(nb)

    return order


def bfs(
    starts: Iterable[T],
    neighbors: NeighborsFn[T],
    *,
    should_expand: ShouldExpandFn[T] | None = None,
) -> list[T]:
    """Iterative breadth-first traversal; each node visited at most once."""
    if should_expand is None:
        should_expand = lambda _node: True

    visited: set[T] = set()
    order: list[T] = []
    queue: deque[T] = deque(starts)

    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        order.append(node)

        if not should_expand(node):
            continue

        for nb in neighbors(node):
            if nb not in visited:
                queue.append(nb)

    return order
