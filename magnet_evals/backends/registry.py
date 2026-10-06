"""Lazy backend registry.

Registry lookups do not import native engine packages. Adapter modules themselves
must preserve that property until ``resolve``/``execute`` requires the engine.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable

from magnet_evals.backends.base import EvaluationBackend
from magnet_evals.errors import EngineCompatibilityError, UnknownEngineError


@dataclass(frozen=True)
class BackendRegistration:
    key: str
    module: str
    factory: str
    experimental: bool = True


_BUILTINS = {
    'harbor': BackendRegistration(
        key='harbor',
        module='magnet_evals.backends.harbor',
        factory='HarborBackend',
    ),
    'helm': BackendRegistration(
        key='helm',
        module='magnet_evals.backends.helm',
        factory='HelmBackend',
    ),
    'olmo_eval': BackendRegistration(
        key='olmo_eval',
        module='magnet_evals.backends.olmo_eval',
        factory='OlmoEvalBackend',
    ),
    'inspect_ai': BackendRegistration(
        key='inspect_ai',
        module='magnet_evals.backends.inspect_ai',
        factory='InspectAIBackend',
    ),
}

_CACHE: dict[str, EvaluationBackend] = {}


def registrations() -> dict[str, BackendRegistration]:
    return dict(_BUILTINS)


def register_backend(registration: BackendRegistration, *, replace: bool = False) -> None:
    if registration.key in _BUILTINS and not replace:
        raise ValueError(f'backend {registration.key!r} is already registered')
    _BUILTINS[registration.key] = registration
    _CACHE.pop(registration.key, None)


def get_backend(key: str) -> EvaluationBackend:
    if key in _CACHE:
        return _CACHE[key]
    try:
        registration = _BUILTINS[key]
    except KeyError as ex:
        known = ', '.join(sorted(_BUILTINS)) or '<none>'
        raise UnknownEngineError(
            f'unknown evaluation engine {key!r}; registered engines: {known}'
        ) from ex
    module = importlib.import_module(registration.module)
    factory: Callable[[], object] = getattr(module, registration.factory)
    backend = factory()
    if not isinstance(backend, EvaluationBackend):
        raise EngineCompatibilityError(
            f'{registration.module}:{registration.factory} does not implement EvaluationBackend'
        )
    _CACHE[key] = backend
    return backend


def clear_backend_cache() -> None:
    _CACHE.clear()
