"""A tiny in-memory TTL cache with a size cap."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable, Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(
        self,
        ttl_s: float,
        max_size: int = 512,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_s
        self._max = max_size
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str) -> V | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._items[key]
            return None
        return value

    def set(self, key: str, value: V) -> None:
        if self._ttl <= 0:
            return
        self._items[key] = (self._clock() + self._ttl, value)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)
