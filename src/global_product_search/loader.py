from __future__ import annotations

import importlib
import inspect
import pkgutil

from .extractors.base import BaseExtractor, Extractor


def discover_extractors() -> list[Extractor]:
    extractors: list[Extractor] = []
    package = importlib.import_module("global_product_search.extractors")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name.startswith("_") or module_name == "base":
            continue
        module = importlib.import_module(f"{package.__name__}.{module_name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not issubclass(obj, BaseExtractor) or obj is BaseExtractor:
                continue
            if obj.__module__ != module.__name__:
                continue
            if obj.__name__.startswith("_") or not obj.__name__.endswith("Extractor"):
                continue
            extractors.append(obj())
    return extractors
