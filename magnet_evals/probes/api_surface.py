from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import Any

from magnet_evals.engines import ENGINE_SPECS
from magnet_evals.probes.model import ProbeRecord, ProbeStatus


@dataclass(frozen=True)
class SymbolCheck:
    module: str
    qualname: str
    purpose: str


API_SURFACES: dict[str, tuple[SymbolCheck, ...]] = {
    'harbor': (
        SymbolCheck('harbor.job', 'Job.create', 'supported native job construction'),
        SymbolCheck('harbor.job', 'Job.run', 'native asynchronous execution and cancellation'),
        SymbolCheck('harbor.models.job.config', 'JobConfig', 'structured native job inputs'),
    ),
    'olmo_eval': (
        SymbolCheck(
            'olmo_eval.runners.asynq.runner',
            'AsyncEvalRunner',
            'native runner used for task lifecycle and scoring',
        ),
        SymbolCheck(
            'olmo_eval.harness.config',
            'HarnessConfig',
            'provider/tool/scaffold/sandbox configuration',
        ),
        SymbolCheck(
            'olmo_eval.runners.common.types',
            'TaskResult',
            'native task result and metric/count representation',
        ),
    ),
    'inspect_ai': (
        SymbolCheck(
            'inspect_ai',
            'eval',
            'public evaluation entry point',
        ),
        SymbolCheck(
            'inspect_ai',
            'eval_retry',
            'public retry entry point; native retry remains optional initially',
        ),
        SymbolCheck(
            'inspect_ai.log',
            'read_eval_log',
            'native log import/reading seam',
        ),
    ),
    'helm': (),
}


def resolve_symbol(module_name: str, qualname: str) -> Any:
    obj: Any = importlib.import_module(module_name)
    for part in qualname.split('.'):
        obj = getattr(obj, part)
    return obj


def probe_api_surface(engine: str) -> list[ProbeRecord]:
    spec = ENGINE_SPECS[engine]
    if importlib.util.find_spec(spec.module) is None:
        return [
            ProbeRecord(
                probe=f'api-surface:{engine}',
                status=ProbeStatus.BLOCKED,
                summary=f'{spec.module} is not installed; API surface not inspected',
                details={'engine': engine},
            )
        ]

    checks = API_SURFACES[engine]
    if not checks:
        return [
            ProbeRecord(
                probe=f'api-surface:{engine}',
                status=ProbeStatus.INFO,
                summary='no generic phase-1 symbol contract is frozen for this engine',
                details={
                    'engine': engine,
                    'reason': 'HELM compatibility is currently fixture/materialization driven',
                },
            )
        ]

    records: list[ProbeRecord] = []
    for check in checks:
        try:
            obj = resolve_symbol(check.module, check.qualname)
        except (ImportError, AttributeError) as ex:
            records.append(
                ProbeRecord(
                    probe=f'api-symbol:{engine}:{check.module}:{check.qualname}',
                    status=ProbeStatus.FAIL,
                    summary=f'missing expected public API symbol: {check.module}.{check.qualname}',
                    details={
                        'engine': engine,
                        'module': check.module,
                        'qualname': check.qualname,
                        'purpose': check.purpose,
                        'error': str(ex),
                    },
                )
            )
        else:
            records.append(
                ProbeRecord(
                    probe=f'api-symbol:{engine}:{check.module}:{check.qualname}',
                    status=ProbeStatus.PASS,
                    summary=f'found {check.module}.{check.qualname}',
                    details={
                        'engine': engine,
                        'module': check.module,
                        'qualname': check.qualname,
                        'purpose': check.purpose,
                        'object_module': getattr(obj, '__module__', None),
                    },
                )
            )
    return records


def probe_all_api_surfaces() -> list[ProbeRecord]:
    records: list[ProbeRecord] = []
    for engine in sorted(ENGINE_SPECS):
        records.extend(probe_api_surface(engine))
    return records
