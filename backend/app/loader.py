"""Loads the implementation chosen in .env for each module, falling back to a safe default."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from types import ModuleType
from typing import Generic, TypeVar

from app.modules.base import Module
from app.schemas import ModuleStatus

log = logging.getLogger(__name__)

M = TypeVar("M", bound=Module)


def instantiate(package: str, spec: str) -> Module:
    """Turn ".mock:MockLipReader" (relative to `package`) into a MockLipReader()."""
    module_name, class_name = spec.split(":")
    return getattr(importlib.import_module(module_name, package), class_name)()


@dataclass
class Slot(Generic[M]):
    """One pipeline stage: the implementation in use plus its always-working fallback."""

    kind: str
    requested: str
    impl: M
    fallback: M
    load_error: str | None = None

    def status(self) -> ModuleStatus:
        return ModuleStatus(
            kind=self.kind,
            requested=self.requested,
            active=self.impl.name,
            fallback=self.impl is self.fallback,
            error=self.load_error,
        )


def load_slot(kind: str, package: ModuleType, requested: str) -> Slot:
    """`package` is a module package exposing IMPLEMENTATIONS and FALLBACK."""
    implementations: dict[str, str] = package.IMPLEMENTATIONS
    fallback = instantiate(package.__name__, implementations[package.FALLBACK])
    fallback.load()
    if requested == package.FALLBACK:
        return Slot(kind, requested, fallback, fallback)

    try:
        if requested not in implementations:
            raise KeyError(f"unknown implementation, options: {', '.join(implementations)}")
        impl = instantiate(package.__name__, implementations[requested])
        impl.load()
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        log.warning("%s: %r unavailable (%s), using %r", kind, requested, error, fallback.name)
        return Slot(kind, requested, fallback, fallback, error)

    log.info("%s: using %r", kind, requested)
    return Slot(kind, requested, impl, fallback)
