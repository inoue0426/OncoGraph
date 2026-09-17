from .base import SourceAdapter


class SourceRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, type[SourceAdapter]] = {}

    def register(self, adapter: type[SourceAdapter]) -> type[SourceAdapter]:
        key = adapter.descriptor.key
        if key in self._adapters:
            raise ValueError(f"Duplicate source adapter: {key}")
        self._adapters[key] = adapter
        return adapter

    def get(self, key: str) -> type[SourceAdapter]:
        return self._adapters[key]

    def descriptors(self):
        return [a.descriptor for a in self._adapters.values()]


registry = SourceRegistry()
