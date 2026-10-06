"""Versioned, dependency-free public contracts for aiq-magnet-evals.

These dataclasses intentionally contain only JSON-shaped scientific inputs and
outputs. Native engine objects never cross this boundary.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, cast, get_args

from magnet_evals.errors import RequestValidationError
from magnet_evals.jsonutil import (
    JSONValue,
    check_secret_name_list,
    find_secret_paths,
    normalize_json,
    normalize_json_object,
)

REQUEST_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1

ExecutionStatus = Literal['succeeded', 'failed', 'cancelled', 'incomplete']
CoverageStatus = Literal['complete', 'partial', 'unknown']


def as_execution_status(value: object) -> ExecutionStatus:
    """Validate and narrow a status string (e.g. native or deserialized)."""
    text = str(value)
    if text not in get_args(ExecutionStatus):
        raise RequestValidationError(f'invalid execution status {text!r}')
    return cast(ExecutionStatus, text)


def as_coverage_status(value: object) -> CoverageStatus:
    text = str(value)
    if text not in get_args(CoverageStatus):
        raise RequestValidationError(f'invalid coverage status {text!r}')
    return cast(CoverageStatus, text)


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise RequestValidationError(f'unknown {label} fields: {sorted(unknown)}')


def _nonnegative_int(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RequestValidationError(f'{label} must be a non-negative integer or null')
    return value



@dataclass(frozen=True)
class ModelBinding:
    """One model/provider role participating in a measurement."""

    role: str
    model: str
    provider: str | None = None
    revision: str | None = None
    cache_token: str | None = None
    provider_options: Mapping[str, Any] = field(default_factory=dict)
    identity_unknown_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reasons = self.identity_unknown_reasons
        if not isinstance(reasons, (tuple, list)) or any(
            not isinstance(reason, str) or not reason.strip() for reason in reasons
        ):
            raise RequestValidationError('model identity_unknown_reasons must be non-empty strings')
        object.__setattr__(self, 'identity_unknown_reasons', tuple(dict.fromkeys(reasons)))
        if not self.role.strip():
            raise RequestValidationError('model role must be non-empty')
        if not self.model.strip():
            raise RequestValidationError(f'model for role {self.role!r} must be non-empty')
        object.__setattr__(self, 'provider_options', normalize_json(dict(self.provider_options)))
        secret_paths = find_secret_paths(self.provider_options, path=f'models.{self.role}.provider_options')
        if secret_paths:
            raise RequestValidationError(
                'credential-bearing values must be supplied through ExecutionContext.env; '
                f'found request keys: {", ".join(secret_paths)}'
            )

    def to_dict(self) -> dict[str, JSONValue]:
        data: dict[str, JSONValue] = {
            'role': self.role,
            'model': self.model,
            'provider': self.provider,
            'revision': self.revision,
            'cache_token': self.cache_token,
            'provider_options': normalize_json(self.provider_options),
        }
        # Preserve existing serialized requests when no uncertainty is supplied.
        if self.identity_unknown_reasons:
            data['identity_unknown_reasons'] = list(self.identity_unknown_reasons)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ModelBinding':
        allowed = {'role', 'model', 'provider', 'revision', 'cache_token', 'provider_options',
                   'identity_unknown_reasons'}
        _reject_unknown(data, allowed, 'model binding')
        return cls(
            role=str(data['role']),
            model=str(data['model']),
            provider=None if data.get('provider') is None else str(data['provider']),
            revision=None if data.get('revision') is None else str(data['revision']),
            cache_token=None if data.get('cache_token') is None else str(data['cache_token']),
            provider_options=dict(data.get('provider_options') or {}),
            identity_unknown_reasons=data.get('identity_unknown_reasons', ()),
        )


@dataclass(frozen=True)
class EvaluationRequest:
    """Serializable description of a native evaluation measurement."""

    engine: str
    task: str
    models: tuple[ModelBinding, ...]
    task_options: Mapping[str, Any] = field(default_factory=dict)
    generation: Mapping[str, Any] = field(default_factory=dict)
    engine_options: Mapping[str, Any] = field(default_factory=dict)
    task_revision: str | None = None
    data_revision: str | None = None
    schema_version: int = REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REQUEST_SCHEMA_VERSION:
            raise RequestValidationError(
                f'unsupported request schema {self.schema_version}; expected {REQUEST_SCHEMA_VERSION}'
            )
        if not self.engine.strip():
            raise RequestValidationError('engine must be non-empty')
        if not self.task.strip():
            raise RequestValidationError('task must be non-empty')
        if not self.models:
            raise RequestValidationError('at least one model binding is required')
        roles = [model.role for model in self.models]
        if len(set(roles)) != len(roles):
            raise RequestValidationError(f'model roles must be unique, got {roles!r}')
        if 'primary' not in roles:
            raise RequestValidationError("one model binding must use role='primary'")
        for name in ('task_options', 'generation', 'engine_options'):
            normalized = normalize_json(dict(getattr(self, name)), path=name)
            object.__setattr__(self, name, normalized)
            secret_paths = find_secret_paths(normalized, path=name)
            if secret_paths:
                raise RequestValidationError(
                    'credential-bearing values must be supplied through ExecutionContext.env; '
                    f'found request keys: {", ".join(secret_paths)}'
                )
        if 'required_secrets' in self.engine_options:
            try:
                check_secret_name_list(
                    self.engine_options['required_secrets'], label='engine_options.required_secrets'
                )
            except ValueError as ex:
                raise RequestValidationError(str(ex)) from ex

    @property
    def primary_model(self) -> ModelBinding:
        return next(model for model in self.models if model.role == 'primary')

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            'schema_version': self.schema_version,
            'engine': self.engine,
            'task': self.task,
            'task_revision': self.task_revision,
            'data_revision': self.data_revision,
            'models': [model.to_dict() for model in self.models],
            'task_options': normalize_json(self.task_options),
            'generation': normalize_json(self.generation),
            'engine_options': normalize_json(self.engine_options),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'EvaluationRequest':
        allowed = {
            'schema_version', 'engine', 'task', 'task_revision', 'data_revision',
            'models', 'task_options', 'generation', 'engine_options',
        }
        _reject_unknown(data, allowed, 'evaluation request')
        models = data.get('models')
        if not isinstance(models, list):
            raise RequestValidationError('models must be a JSON list')
        return cls(
            schema_version=int(data.get('schema_version', REQUEST_SCHEMA_VERSION)),
            engine=str(data['engine']),
            task=str(data['task']),
            task_revision=None if data.get('task_revision') is None else str(data['task_revision']),
            data_revision=None if data.get('data_revision') is None else str(data['data_revision']),
            models=tuple(ModelBinding.from_dict(item) for item in models),
            task_options=dict(data.get('task_options') or {}),
            generation=dict(data.get('generation') or {}),
            engine_options=dict(data.get('engine_options') or {}),
        )


@dataclass(frozen=True)
class ExecutionContext:
    """Operational inputs that must not change measurement identity."""

    output_dir: Path
    env: Mapping[str, str] = field(default_factory=dict)
    worker_python: str | None = None
    timeout_seconds: float | None = None
    #: Operational endpoint override per model role (role -> base URL), e.g. a
    #: leased serving endpoint whose URL varies per lease. It never enters
    #: identity; the binding's ``revision``/``cache_token`` names the model.
    model_endpoints: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'output_dir', Path(self.output_dir).expanduser().resolve())
        object.__setattr__(self, 'env', {str(k): str(v) for k, v in self.env.items()})
        object.__setattr__(
            self, 'model_endpoints', {str(k): str(v) for k, v in self.model_endpoints.items()}
        )
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise RequestValidationError('timeout_seconds must be positive')

    def public_dict(self) -> dict[str, JSONValue]:
        """Return persistable context metadata without secret values."""
        return normalize_json_object(
            {
                'output_dir': str(self.output_dir),
                'env_keys': sorted(self.env),
                'worker_python': self.worker_python,
                'timeout_seconds': self.timeout_seconds,
                'model_endpoint_roles': sorted(self.model_endpoints),
            }
        )


@dataclass(frozen=True)
class MeasurementIdentity:
    algorithm: str
    digest: str
    reusable: bool
    unknown_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.algorithm.strip():
            raise RequestValidationError('measurement identity algorithm must be non-empty')
        if len(self.digest) != 64 or any(ch not in '0123456789abcdefABCDEF' for ch in self.digest):
            raise RequestValidationError('measurement identity digest must be 64 hexadecimal characters')
        if self.reusable and self.unknown_reasons:
            raise RequestValidationError('reusable identity cannot have unknown identity reasons')

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            'algorithm': self.algorithm,
            'digest': self.digest,
            'reusable': self.reusable,
            'unknown_reasons': list(self.unknown_reasons),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'MeasurementIdentity':
        _reject_unknown(data, {'algorithm', 'digest', 'reusable', 'unknown_reasons'}, 'measurement identity')
        return cls(
            algorithm=str(data['algorithm']),
            digest=str(data['digest']),
            reusable=bool(data['reusable']),
            unknown_reasons=tuple(str(x) for x in data.get('unknown_reasons', [])),
        )


@dataclass(frozen=True)
class ResolvedEvaluation:
    request: EvaluationRequest
    adapter_version: str
    engine_version: str | None
    native_config: Mapping[str, Any]
    identity: MeasurementIdentity
    resolved_facts: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'native_config', normalize_json(dict(self.native_config)))
        object.__setattr__(self, 'resolved_facts', normalize_json(dict(self.resolved_facts)))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            'request': self.request.to_dict(),
            'adapter_version': self.adapter_version,
            'engine_version': self.engine_version,
            'native_config': normalize_json(self.native_config),
            'identity': self.identity.to_dict(),
            'resolved_facts': normalize_json(self.resolved_facts),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ResolvedEvaluation':
        _reject_unknown(
            data,
            {'request', 'adapter_version', 'engine_version', 'native_config', 'identity', 'resolved_facts'},
            'resolved evaluation',
        )
        return cls(
            request=EvaluationRequest.from_dict(data['request']),
            adapter_version=str(data['adapter_version']),
            engine_version=None if data.get('engine_version') is None else str(data['engine_version']),
            native_config=dict(data.get('native_config') or {}),
            identity=MeasurementIdentity.from_dict(data['identity']),
            resolved_facts=dict(data.get('resolved_facts') or {}),
        )


@dataclass(frozen=True)
class CoverageFacts:
    status: CoverageStatus = 'unknown'
    expected: int | None = None
    processed: int | None = None
    saved: int | None = None
    failed: int | None = None

    def __post_init__(self) -> None:
        if self.status not in {'complete', 'partial', 'unknown'}:
            raise RequestValidationError(f'invalid coverage status {self.status!r}')
        for name in ('expected', 'processed', 'saved', 'failed'):
            _nonnegative_int(getattr(self, name), label=f'coverage.{name}')

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            'status': self.status,
            'expected': self.expected,
            'processed': self.processed,
            'saved': self.saved,
            'failed': self.failed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'CoverageFacts':
        _reject_unknown(data, {'status', 'expected', 'processed', 'saved', 'failed'}, 'coverage')
        return cls(
            status=as_coverage_status(data.get('status', 'unknown')),
            expected=_nonnegative_int(data.get('expected'), label='coverage.expected'),
            processed=_nonnegative_int(data.get('processed'), label='coverage.processed'),
            saved=_nonnegative_int(data.get('saved'), label='coverage.saved'),
            failed=_nonnegative_int(data.get('failed'), label='coverage.failed'),
        )


@dataclass(frozen=True)
class MetricRecord:
    task: str
    model_role: str
    metric: str
    value: float
    scorer: str | None = None
    score: str | None = None
    group: str | None = None
    reducer: str | None = None
    denominator: int | None = None

    def __post_init__(self) -> None:
        if not self.task.strip() or not self.model_role.strip() or not self.metric.strip():
            raise RequestValidationError('metric task, model_role, and metric must be non-empty')
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not math.isfinite(float(self.value)):
            raise RequestValidationError('metric value must be a finite number')
        # Canonical float, so serialization round-trips (int 1 would reload as
        # 1.0 and break the normalized-artifact identity check).
        object.__setattr__(self, 'value', float(self.value))
        if self.denominator is not None:
            _nonnegative_int(self.denominator, label='metric denominator')

    def to_dict(self) -> dict[str, JSONValue]:
        data: dict[str, JSONValue] = {
            'task': self.task,
            'model_role': self.model_role,
            'metric': self.metric,
            'scorer': self.scorer,
            'reducer': self.reducer,
            'value': self.value,
            'denominator': self.denominator,
        }
        # ``score`` and ``group`` were added after the phase-2 fixtures were
        # captured. Omit them when absent so those fixtures retain their
        # byte-derived normalized artifact identity.
        if self.score is not None:
            data['score'] = self.score
        if self.group is not None:
            data['group'] = self.group
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'MetricRecord':
        _reject_unknown(
            data,
            {
                'task', 'model_role', 'metric', 'scorer', 'score', 'group',
                'reducer', 'value', 'denominator',
            },
            'metric record',
        )
        return cls(
            task=str(data['task']),
            model_role=str(data['model_role']),
            metric=str(data['metric']),
            scorer=None if data.get('scorer') is None else str(data['scorer']),
            score=None if data.get('score') is None else str(data['score']),
            group=None if data.get('group') is None else str(data['group']),
            reducer=None if data.get('reducer') is None else str(data['reducer']),
            value=float(data['value']),
            denominator=None if data.get('denominator') is None else int(data['denominator']),
        )


@dataclass(frozen=True)
class SampleRecord:
    """Dependency-free normalized view of one native sample/prediction.

    ``scores`` and ``trajectory`` remain structured JSON. The adapter may also
    retain a small native metadata mapping when no common field exists yet; raw
    native files remain authoritative and are checksummed separately.
    """

    task: str
    model_role: str
    sample_id: str
    epoch: int | None = None
    scores: Mapping[str, Any] = field(default_factory=dict)
    trajectory: Any = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    native: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task.strip() or not self.model_role.strip() or not self.sample_id.strip():
            raise RequestValidationError('sample task, model_role, and sample_id must be non-empty')
        if self.epoch is not None:
            _nonnegative_int(self.epoch, label='sample epoch')
        object.__setattr__(self, 'scores', normalize_json(dict(self.scores)))
        object.__setattr__(self, 'trajectory', normalize_json(self.trajectory))
        object.__setattr__(self, 'usage', normalize_json(dict(self.usage)))
        object.__setattr__(self, 'native', normalize_json(dict(self.native)))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            'task': self.task,
            'model_role': self.model_role,
            'sample_id': self.sample_id,
            'epoch': self.epoch,
            'scores': normalize_json(self.scores),
            'trajectory': normalize_json(self.trajectory),
            'usage': normalize_json(self.usage),
            'native': normalize_json(self.native),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'SampleRecord':
        _reject_unknown(
            data,
            {'task', 'model_role', 'sample_id', 'epoch', 'scores', 'trajectory', 'usage', 'native'},
            'sample record',
        )
        return cls(
            task=str(data['task']),
            model_role=str(data['model_role']),
            sample_id=str(data['sample_id']),
            epoch=None if data.get('epoch') is None else int(data['epoch']),
            scores=dict(data.get('scores') or {}),
            trajectory=data.get('trajectory'),
            usage=dict(data.get('usage') or {}),
            native=dict(data.get('native') or {}),
        )


@dataclass(frozen=True)
class ArtifactReference:
    path: str
    sha256: str
    size_bytes: int
    role: str

    def __post_init__(self) -> None:
        from pathlib import PurePosixPath

        pure = PurePosixPath(self.path)
        if pure.is_absolute() or '..' in pure.parts or self.path in ('', '.'):
            raise RequestValidationError(f'artifact path must be safe and relative: {self.path!r}')
        if len(self.sha256) != 64 or any(ch not in '0123456789abcdefABCDEF' for ch in self.sha256):
            raise RequestValidationError(f'artifact sha256 must be 64 hex characters: {self.sha256!r}')
        if self.size_bytes < 0:
            raise RequestValidationError('artifact size_bytes must be non-negative')
        if not self.role.strip():
            raise RequestValidationError('artifact role must be non-empty')

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            'path': self.path,
            'sha256': self.sha256,
            'size_bytes': self.size_bytes,
            'role': self.role,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ArtifactReference':
        _reject_unknown(data, {'path', 'sha256', 'size_bytes', 'role'}, 'artifact reference')
        return cls(
            path=str(data['path']),
            sha256=str(data['sha256']),
            size_bytes=int(data['size_bytes']),
            role=str(data['role']),
        )


@dataclass(frozen=True)
class ResultRecord:
    task: str
    model_role: str
    metrics: tuple[MetricRecord, ...]
    coverage: CoverageFacts = field(default_factory=CoverageFacts)
    primary_metric: str | None = None
    native_status: str | None = None
    error: str | None = None
    native_config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task.strip() or not self.model_role.strip():
            raise RequestValidationError('result task and model_role must be non-empty')
        for metric in self.metrics:
            if metric.task != self.task or metric.model_role != self.model_role:
                raise RequestValidationError('result metric scope does not match its parent result record')
        object.__setattr__(self, 'native_config', normalize_json(dict(self.native_config)))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            'task': self.task,
            'model_role': self.model_role,
            'metrics': [metric.to_dict() for metric in self.metrics],
            'coverage': self.coverage.to_dict(),
            'primary_metric': self.primary_metric,
            'native_status': self.native_status,
            'error': self.error,
            'native_config': normalize_json(self.native_config),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ResultRecord':
        _reject_unknown(
            data,
            {'task', 'model_role', 'metrics', 'coverage', 'primary_metric', 'native_status', 'error', 'native_config'},
            'result record',
        )
        return cls(
            task=str(data['task']),
            model_role=str(data['model_role']),
            metrics=tuple(MetricRecord.from_dict(x) for x in data.get('metrics', [])),
            coverage=CoverageFacts.from_dict(data.get('coverage') or {}),
            primary_metric=None if data.get('primary_metric') is None else str(data['primary_metric']),
            native_status=None if data.get('native_status') is None else str(data['native_status']),
            error=None if data.get('error') is None else str(data['error']),
            native_config=dict(data.get('native_config') or {}),
        )


@dataclass(frozen=True)
class EvaluationResult:
    engine: str
    identity: MeasurementIdentity
    status: ExecutionStatus
    records: tuple[ResultRecord, ...]
    samples: tuple[SampleRecord, ...] = ()
    artifacts: tuple[ArtifactReference, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESULT_SCHEMA_VERSION:
            raise RequestValidationError(
                f'unsupported result schema {self.schema_version}; expected {RESULT_SCHEMA_VERSION}'
            )
        if not self.engine.strip():
            raise RequestValidationError('result engine must be non-empty')
        if self.status not in {'succeeded', 'failed', 'cancelled', 'incomplete'}:
            raise RequestValidationError(f'invalid execution status {self.status!r}')
        if self.status == 'succeeded' and not self.records:
            raise RequestValidationError('a succeeded evaluation result must contain at least one result record')
        object.__setattr__(self, 'diagnostics', normalize_json(dict(self.diagnostics)))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            'schema_version': self.schema_version,
            'engine': self.engine,
            'identity': self.identity.to_dict(),
            'status': self.status,
            'records': [record.to_dict() for record in self.records],
            'samples': [sample.to_dict() for sample in self.samples],
            'artifacts': [artifact.to_dict() for artifact in self.artifacts],
            'diagnostics': normalize_json(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'EvaluationResult':
        _reject_unknown(
            data,
            {'schema_version', 'engine', 'identity', 'status', 'records', 'samples', 'artifacts', 'diagnostics'},
            'evaluation result',
        )
        return cls(
            schema_version=int(data.get('schema_version', RESULT_SCHEMA_VERSION)),
            engine=str(data['engine']),
            identity=MeasurementIdentity.from_dict(data['identity']),
            status=as_execution_status(data['status']),
            records=tuple(ResultRecord.from_dict(x) for x in data.get('records', [])),
            samples=tuple(SampleRecord.from_dict(x) for x in data.get('samples', [])),
            artifacts=tuple(ArtifactReference.from_dict(x) for x in data.get('artifacts', [])),
            diagnostics=dict(data.get('diagnostics') or {}),
        )
