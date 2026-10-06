"""Static metadata for evaluation engines and their phase-1 verified pins.

``verified`` means the pin passed the native fixtures recorded in
``docs/planning/phase1-evidence.md``, for the tested combinations in
``docs/planning/phase1-capabilities.md`` only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PinState = Literal['unresolved', 'candidate', 'verified']


@dataclass(frozen=True)
class EngineSpec:
    """Phase-1 metadata for one evaluation engine."""

    key: str
    distribution: str
    module: str
    repository: str
    candidate_revision: str | None
    candidate_version: str | None
    pin_state: PinState
    python_requirement_hint: str | None
    research_notes: tuple[str, ...] = ()


ENGINE_SPECS: dict[str, EngineSpec] = {
    'harbor': EngineSpec(
        key='harbor', distribution='harbor', module='harbor',
        repository='https://github.com/harbor-framework/harbor.git',
        candidate_revision='1e5c5c6db929a10a140d05e606882c671ae20729',
        candidate_version='0.23.0', pin_state='candidate',
        python_requirement_hint='>=3.12; isolated worker',
        research_notes=(
            'Native synthetic Docker probes: docs/planning/harbor-evidence.md.',
            'SWE-bench Verified/Pro benchmark acceptance remains open.',
        ),
    ),
    'helm': EngineSpec(
        key='helm',
        distribution='crfm-helm',
        module='helm',
        repository='https://github.com/stanford-crfm/helm.git',
        candidate_revision=None,
        candidate_version='0.5.14',
        pin_state='verified',
        python_requirement_hint='CPython 3.12.3 tested (isolated worker)',
        research_notes=(
            'Verified 2026-09-29 through MAGNET 7bb105ab1c85bfaa01bf68c97ff7523332479ee4.',
            'Fresh execution proven with the local simple model only; import/reuse of historical runs.',
            'Constraints: dev/environments/phase1/helm-py312-constraints.txt.',
            'aiq-magnet-evals HELM adapter (phase 5) runs `python -m helm.benchmark.run` in a worker.',
        ),
    ),
    'olmo_eval': EngineSpec(
        key='olmo_eval',
        distribution='olmo-eval',
        module='olmo_eval',
        repository='https://github.com/allenai/olmo-eval.git',
        candidate_revision='73ade80e24f796af55caeb8fd7b75a7f3fd607fd',
        candidate_version=None,
        pin_state='verified',
        python_requirement_hint='>=3.12; CPython 3.12.3 tested',
        research_notes=(
            'Verified 2026-09-29 as an isolated worker checkout synced from its frozen uv.lock.',
            'The eval_audit prototype revision c84828e4af096004c561b668b68e0b126c7f60e9 is not supported.',
            'The adapter verifies the executing checkout against upstream_revision.',
        ),
    ),
    'inspect_ai': EngineSpec(
        key='inspect_ai',
        distribution='inspect-ai',
        module='inspect_ai',
        repository='https://github.com/UKGovernmentBEIS/inspect_ai.git',
        candidate_revision=None,
        candidate_version='0.3.272',
        pin_state='verified',
        python_requirement_hint='>=3.10; CPython 3.11.15 tested',
        research_notes=(
            'Verified 2026-09-29 with a local fixture provider through public eval/log APIs.',
            'Constraints: dev/environments/phase1/inspect-py311-constraints.txt.',
            'Only the local sandbox is tested; Docker sandboxes are untested.',
            'Task factories, agents, scorers, and tools may execute arbitrary Python.',
        ),
    ),
}


def get_engine_spec(key: str) -> EngineSpec:
    """Return an engine spec or raise with the supported names."""
    try:
        return ENGINE_SPECS[key]
    except KeyError as ex:
        known = ', '.join(sorted(ENGINE_SPECS))
        raise KeyError(f'unknown engine {key!r}; expected one of: {known}') from ex
