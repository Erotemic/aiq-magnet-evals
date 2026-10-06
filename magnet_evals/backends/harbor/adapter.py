"""Generic, isolated Harbor job execution preserving native task semantics."""
from __future__ import annotations

import asyncio
import contextlib
import copy
import importlib
import importlib.metadata
import inspect
import os
import platform
import re
import subprocess
from pathlib import Path

from magnet_evals.backends.harbor.bridge import endpoint_bridge
from magnet_evals.backends.harbor.normalize import normalize_harbor_job
from magnet_evals.backends.harbor.ownership import cleanup_owned_docker, record_project
from magnet_evals.contracts import (
    EvaluationRequest,
    ExecutionContext,
    ResolvedEvaluation,
)
from magnet_evals.errors import (
    ArtifactError,
    EngineCompatibilityError,
    MissingDependencyError,
    RequestValidationError,
)
from magnet_evals.identity import adapter_source_digest, build_measurement_identity
from magnet_evals.jsonutil import sha256_file, sha256_json

ADAPTER_VERSION = '0.1.0'
CANDIDATE_HARBOR_VERSION = '0.23.0'
_TASK_OPTIONS = {'agent', 'agent_kwargs', 'agent_revision', 'task_ids', 'environment',
                 'n_concurrent', 'n_attempts', 'endpoint_location'}
_ENGINE_OPTIONS = {'job_options', 'registration_modules', 'required_secrets', 'checksums',
                   'execution_protocol', 'protocol_options'}
_JOB_OPTIONS = {'timeout_multiplier', 'agent_timeout_multiplier', 'verifier_timeout_multiplier',
                'agent_setup_timeout_multiplier', 'environment_build_timeout_multiplier', 'debug', 'artifacts'}
_PROTECTED_AGENT_KWARGS = {'logs_dir', 'task_dir', 'trial_paths', 'model_name', 'extra_env',
                         'session_id', 'context_id', 'environment', 'kwargs', 'base_url', 'api_base'}


def tree_digest(root: Path, *, python_only=False) -> str:
    entries = []
    for path in sorted(root.rglob('*')):
        if '.git' in path.relative_to(root).parts or '__pycache__' in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise RequestValidationError(f'cannot identify Harbor source containing symlinks: {path}')
        if path.is_file() and (not python_only or path.suffix == '.py'):
            entries.append([path.relative_to(root).as_posix(), sha256_file(path)])
    if not entries:
        raise RequestValidationError(f'Harbor source has no identifiable files: {root}')
    return sha256_json(entries)


def _runtime():
    try:
        version = importlib.metadata.version('harbor')
        AgentFactory = importlib.import_module('harbor.agents.factory').AgentFactory
        Job = importlib.import_module('harbor.job').Job
        JobConfig = importlib.import_module('harbor.models.job.config').JobConfig
    except ImportError as exc:
        raise MissingDependencyError('Harbor requires an isolated Python >=3.12 worker with harbor==0.23.0') from exc
    if version != CANDIDATE_HARBOR_VERSION:
        raise EngineCompatibilityError(f'Harbor candidate pin is {CANDIDATE_HARBOR_VERSION}; got {version}')
    return Job, JobConfig, AgentFactory, version


def _module_source(module) -> Path:
    source = module.__file__
    if not source:
        raise EngineCompatibilityError('Harbor integration requires identifiable Python implementation source')
    return Path(source).resolve()


def _execution_protocol(request):
    reference = request.engine_options.get('execution_protocol')
    if reference is None:
        return None
    module, name = reference[7:].split(':')
    return getattr(importlib.import_module(module), name)()


def _dependency_versions() -> dict[str, str]:
    """Identify installed Harbor dependencies, including installed optional ones.

    Missing extras are not runtime inputs. Including an installed extra is
    conservative: changing its version must not reuse earlier evidence.
    """
    pending, versions = ['harbor'], {}
    while pending:
        name = re.sub(r'[-_.]+', '-', pending.pop()).lower()
        if name in versions:
            continue
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        versions[name] = distribution.version
        for requirement in distribution.requires or []:
            match = re.match(r'[A-Za-z0-9][A-Za-z0-9_.-]*', requirement)
            if match:
                pending.append(match.group())
    return dict(sorted(versions.items()))


def _validate_agent_kwargs(cls, kwargs):
    if cls.options_model is not None:
        cls.parse_options(kwargs)
        return
    # BaseAgent otherwise silently discards unknown kwargs. External agents
    # without an options model must declare their supported constructor options.
    accepted = set()
    for base in cls.__mro__:
        for name, parameter in inspect.signature(base.__init__).parameters.items():
            if parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
                accepted.add(name)
    unknown = set(kwargs) - accepted
    if unknown:
        raise RequestValidationError(f'unknown Harbor agent options: {sorted(unknown)}')


def _verify_checksums(path: Path, tasks: list[Path]) -> str:
    """Verify upstream SHA256SUMS without shelling out or trusting relative paths."""
    root = path.parent.resolve()
    verified = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]):
            raise RequestValidationError(f'invalid checksum record in {path}')
        relative = parts[1].lstrip('*')
        target = root / relative
        if not target.resolve().is_relative_to(root) or target.is_symlink() or not target.is_file():
            raise RequestValidationError(f'unsafe or missing checksum source: {relative}')
        if sha256_file(target) != parts[0].lower():
            raise RequestValidationError(f'benchmark checksum mismatch: {relative}')
        verified.add(target.resolve())
    for task in tasks:
        for source in task.rglob('*'):
            if source.is_file() and '__pycache__' not in source.relative_to(task).parts and source.resolve() not in verified:
                raise RequestValidationError(f'benchmark checksum manifest does not cover selected task file: {source}')
    return sha256_file(path)


def _agent_option_content(value, *, root: Path, label: str, identities: dict, paths: list, path=()):
    """Resolve explicit file inputs and replace their paths with content identity."""
    if isinstance(value, dict):
        return {key: _agent_option_content(item, root=root, label=label, identities=identities,
            paths=paths, path=(*path, key)) for key, item in value.items()}
    if isinstance(value, list):
        # Lists of opaque paths cannot be excluded by key paths safely.
        return value
    if isinstance(value, str) and path and (path[-1].endswith(('_file', '_path')) or path[-1] == 'source_job'):
        target = Path(value).expanduser()
        if not target.is_absolute():
            target = root / target
        if not target.exists():
            raise RequestValidationError(f'Harbor {label}.{path[-1]} input does not exist: {target}')
        if target.is_symlink():
            raise RequestValidationError(f'Harbor file input cannot be a symlink: {target}')
        identities['.'.join(path)] = tree_digest(target) if target.is_dir() else sha256_file(target)
        paths.append(path)
        return str(target.resolve())
    return value


class HarborBackend:
    key = 'harbor'
    adapter_version = ADAPTER_VERSION

    def capabilities(self):
        return {'experimental': True, 'implementation_status': 'candidate',
                'candidate_version': CANDIDATE_HARBOR_VERSION, 'requires_worker_process': True,
                'capability_scope': 'native fixtures listed in docs/planning/harbor-evidence.md',
                'features': {'native_import': {'implemented': True, 'native_verified': False},
                             'agentic': {'implemented': True, 'native_verified': False},
                             'sandboxing': {'implemented': True, 'native_verified': False}}}

    def validate_request(self, request: EvaluationRequest):
        if request.engine != self.key or not request.task.startswith('path:') or not request.task[5:]:
            raise RequestValidationError('Harbor requires engine=harbor and a path: local task collection')
        if len(request.models) != 1:
            raise RequestValidationError('Harbor currently supports one primary model per native job')
        if set(request.task_options) - _TASK_OPTIONS:
            raise RequestValidationError(f'unknown Harbor task_options: {sorted(set(request.task_options) - _TASK_OPTIONS)}')
        if set(request.engine_options) - _ENGINE_OPTIONS:
            raise RequestValidationError(f'unknown Harbor engine_options: {sorted(set(request.engine_options) - _ENGINE_OPTIONS)}')
        protocol = request.engine_options.get('execution_protocol')
        if protocol is not None and (not isinstance(protocol, str) or not re.fullmatch(r'python:[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*', protocol)):
            raise RequestValidationError('Harbor execution_protocol must be python:module:Class')
        if not isinstance(request.engine_options.get('protocol_options', {}), dict) or (request.engine_options.get('protocol_options') and protocol is None):
            raise RequestValidationError('Harbor protocol_options require an execution protocol')
        job_options = request.engine_options.get('job_options', {})
        if not isinstance(job_options, dict) or set(job_options) - _JOB_OPTIONS:
            raise RequestValidationError('unsupported/protected Harbor job_options; the adapter owns tasks, outputs, agents, and retry policy')
        kwargs = request.task_options.get('agent_kwargs', {})
        if not isinstance(kwargs, dict) or (set(kwargs) | set(request.generation)) & _PROTECTED_AGENT_KWARGS:
            raise RequestValidationError('protected or invalid Harbor agent_kwargs')
        for key in ('n_attempts', 'n_concurrent'):
            value = request.task_options.get(key, 1)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise RequestValidationError(f'Harbor {key} must be a positive integer')
        ids = request.task_options.get('task_ids')
        if ids is not None and (not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not i or '/' in i or i in ('.', '..') for i in ids) or len(ids) != len(set(ids))):
            raise RequestValidationError('Harbor task_ids must be a nonempty list of unique task directory names')
        modules = request.engine_options.get('registration_modules', [])
        if not isinstance(modules, list) or any(not isinstance(m, str) or not m for m in modules):
            raise RequestValidationError('Harbor registration_modules must be a list of importable module names')
        if request.task_options.get('environment', 'docker') != 'docker':
            raise RequestValidationError('Only the Docker Harbor environment has been probed')
        if request.task_options.get('endpoint_location', 'sandbox') not in ('host', 'sandbox'):
            raise RequestValidationError('Harbor endpoint_location must be host or sandbox')
        if set(request.primary_model.provider_options) - {'base_url'}:
            raise RequestValidationError('Harbor provider options only support operational base_url; generation belongs in generation')
        agent = request.task_options.get('agent', 'oracle')
        if not isinstance(agent, str) or not agent:
            raise RequestValidationError('Harbor agent must be a built-in name or python:module:Class')
        if agent.startswith('python:') and len(agent[7:].split(':')) != 2:
            raise RequestValidationError('Harbor python agent must use python:module:Class')
        if set(kwargs) & set(request.generation):
            raise RequestValidationError('Harbor generation and agent_kwargs must not overlap')

    def resolve(self, request: EvaluationRequest):
        self.validate_request(request)
        _Job, JobConfig, AgentFactory, version = _runtime()
        root = Path(request.task[5:]).expanduser().resolve()
        if not root.is_dir():
            raise RequestValidationError(f'Harbor task source is not a directory: {root}')
        tasks = [root] if (root / 'task.toml').is_file() else sorted(p for p in root.iterdir() if p.is_dir() and (p / 'task.toml').is_file())
        wanted = request.task_options.get('task_ids')
        if wanted is not None:
            missing = set(wanted) - {p.name for p in tasks}
            if missing:
                raise RequestValidationError(f'Harbor task ids not found: {sorted(missing)}')
            tasks = [p for p in tasks if p.name in wanted]
        if not tasks:
            raise RequestValidationError('Harbor task source contains no selected task.toml directories')
        task_digests = {p.name: tree_digest(p) for p in tasks}
        content = sha256_json(list(task_digests.items()))
        if request.task_revision and re.fullmatch(r'[0-9a-fA-F]{40}', request.task_revision):
            try:
                head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, timeout=10).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                raise RequestValidationError('Harbor benchmark git revision cannot be verified') from exc
            if head.lower() != request.task_revision.lower():
                raise RequestValidationError('Harbor benchmark checkout does not match task_revision')
        option_digests, option_paths = {}, []
        kwargs = _agent_option_content({**request.task_options.get('agent_kwargs', {}), **request.generation},
            root=Path.cwd(), label='agent_kwargs', identities=option_digests, paths=option_paths)
        reference = request.task_options.get('agent', 'oracle')
        agent = {'import_path': reference[7:]} if reference.startswith('python:') else {'name': reference}
        binding = request.primary_model
        model = binding.model
        if binding.provider and not model.startswith(binding.provider + '/'):
            model = binding.provider + '/' + model
        agent.update(model_name=model, kwargs=kwargs)
        config = JobConfig.model_validate({
            **request.engine_options.get('job_options', {}),
            'n_attempts': request.task_options.get('n_attempts', 1),
            'n_concurrent_trials': request.task_options.get('n_concurrent', 1),
            'retry': {'max_retries': 0}, 'quiet': True,
            'environment': {'type': 'docker', 'delete': True},
            'agents': [agent], 'tasks': [{'path': str(p)} for p in tasks],
        })
        cls = AgentFactory.get_agent_class_from_config(config.agents[0])
        # Validate supported agent options without credential-dependent preflight.
        _validate_agent_kwargs(cls, kwargs)
        source = Path(inspect.getfile(cls)).resolve()
        Task = importlib.import_module('harbor.models.task.task').Task
        native_tasks = {path.name: Task(task_dir=path) for path in tasks}
        unknown_reasons = []
        try:
            docker_runtime = subprocess.check_output(['docker', 'version', '--format',
                '{{.Server.Os}}/{{.Server.Arch}}/{{.Server.Version}}'], text=True, timeout=10).strip()
        except (OSError, subprocess.SubprocessError):
            docker_runtime = None
            unknown_reasons.append('Docker daemon runtime cannot be identified')
        identities = {'task_source_sha256': content,
            'selected_tasks': [p.name for p in tasks],
            'native_task_names': [task.name for task in native_tasks.values()],
            'sandbox_images': {name: task.config.environment.docker_image for name, task in native_tasks.items()},
            'docker_runtime': docker_runtime,
            'agent_source_sha256': tree_digest(source.parent, python_only=True),
            'agent_option_content': option_digests,
            'adapter_source_sha256': adapter_source_digest(__package__),
            'runtime_dependencies': _dependency_versions(),
            'python_runtime': platform.python_implementation() + '/' + platform.python_version(),
            'harbor_source_sha256': tree_digest(_module_source(importlib.import_module('harbor')).parent, python_only=True)}
        checksums = request.engine_options.get('checksums')
        if checksums:
            checksum_path = Path(checksums).expanduser().resolve()
            identities['benchmark_checksums_sha256'] = _verify_checksums(checksum_path, tasks)
            if request.data_revision and request.data_revision.startswith('sha256:') and request.data_revision != 'sha256:' + identities['benchmark_checksums_sha256']:
                raise RequestValidationError('Harbor data_revision does not match the supplied SHA256SUMS')
        module_sources = {}
        for name in request.engine_options.get('registration_modules', []):
            module = importlib.import_module(name)
            module_sources[name] = tree_digest(_module_source(module).parent, python_only=True)
        identities['registration_sources'] = module_sources
        protocol = _execution_protocol(request)
        image_pins = {}
        if protocol is not None:
            protocol_source = Path(inspect.getfile(type(protocol))).resolve()
            protocol_facts = protocol.resolve_facts(request, config.model_dump(mode='json'), tasks)
            if not isinstance(protocol_facts, dict):
                raise RequestValidationError('Harbor execution protocol must resolve a facts object')
            image_pins = protocol_facts.get('image_ids', {})
            identities['execution_protocol'] = {
                'source_sha256': tree_digest(protocol_source.parent, python_only=True),
                'facts': protocol_facts,
            }
        for name, task in native_tasks.items():
            image = task.config.environment.docker_image or ''
            if not re.search(r'(?:@sha256:|^sha256:)[0-9a-f]{64}$', image) and not re.fullmatch(r'sha256:[0-9a-f]{64}', str(image_pins.get(name, ''))):
                unknown_reasons.append(f'Harbor sandbox image/build runtime is not pinned: {name}')
        native = config.model_dump(mode='json', exclude={'job_name', 'jobs_dir'})
        # Pydantic serializes RetryConfig sets as arrays in hash-randomized order.
        # Even with retries disabled, those defaults must serialize deterministically.
        for name in ('include_exceptions', 'exclude_exceptions'):
            if native['retry'].get(name) is not None:
                native['retry'][name] = sorted(native['retry'][name])
        facts = {'engine_version': version, 'task_source_path': str(root), 'identity_facts': identities,
                 'task_content': task_digests,
                 'agent_option_paths': [list(path) for path in option_paths],
                 'endpoint_location': request.task_options.get('endpoint_location', 'sandbox')}
        BaseInstalledAgent = importlib.import_module('harbor.agents.installed.base').BaseInstalledAgent
        if issubclass(cls, BaseInstalledAgent):
            # A package version alone does not freeze its in-container Python,
            # dependencies or setup downloads. Never reuse it as immutable.
            unknown_reasons.append('installed agent sandbox runtime is not fully pinned')
        if unknown_reasons:
            facts['identity_unknown_reasons'] = unknown_reasons
        # Native tasks/agent kwargs contain operational paths; their bytes are
        # present in identity_facts. Drop path copies, retaining scalar behavior.
        identity_native = dict(native)
        identity_native['tasks'] = [{'name': p.name} for p in tasks]
        identity_native['agents'] = [dict(agent)]
        identity_kwargs = copy.deepcopy(kwargs)
        for path in option_paths:
            target = identity_kwargs
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = {'content_sha256': option_digests['.'.join(path)]}
        identity_native['agents'][0]['kwargs'] = identity_kwargs
        identity = build_measurement_identity(request, adapter_version=self.adapter_version,
            engine_version=version, native_config=identity_native, resolved_facts=facts, identity_facts=identities,
            operational_request_paths=[('task',), ('engine_options', 'checksums'),
                *(('task_options', 'agent_kwargs', *path) for path in option_paths),
                *(('generation', *path) for path in option_paths)],
        )
        return ResolvedEvaluation(request=request, adapter_version=self.adapter_version, engine_version=version,
                                  native_config=native, identity=identity, resolved_facts=facts)

    async def execute(self, resolved: ResolvedEvaluation, context: ExecutionContext):
        protocol = _execution_protocol(resolved.request)
        if protocol is not None:
            return await protocol.execute(self, resolved, context)
        return await self.execute_job(resolved, context)

    async def execute_job(self, resolved: ResolvedEvaluation, context: ExecutionContext, *,
                          job_name='evaluation', environment_started_hook=None, agent_started_hook=None):
        """One owned native job; execution protocols may compose named phases."""
        if not re.fullmatch(r'[A-Za-z0-9_-]+', job_name):
            raise RequestValidationError('invalid owned Harbor job name')
        if context.env:
            raise RequestValidationError('Harbor credentials must be supplied through the owned worker environment')
        if set(context.model_endpoints) - {'primary'}:
            raise RequestValidationError('Harbor only supports the primary endpoint')
        Job, JobConfig, _Factory, _version = _runtime()
        current = self.resolve(resolved.request)
        if current.identity.digest != resolved.identity.digest:
            raise RequestValidationError('Harbor source/config changed after resolution; resolve and schedule again')
        root = context.output_dir / 'native/harbor'
        root.mkdir(parents=True, exist_ok=True)
        inputs_root = root if job_name == 'evaluation' else root / (job_name + '-inputs')
        native = dict(resolved.native_config)
        # JSON-shaped deep copy: endpoint injection never mutates resolved inputs.
        native = copy.deepcopy(native)
        import shutil
        for task in native['tasks']:
            path = Path(task['path'])
            snapshot = inputs_root / 'inputs' / path.name
            shutil.copytree(path, snapshot)
            if tree_digest(snapshot) != resolved.resolved_facts['task_content'][path.name]:
                raise RequestValidationError('Harbor task changed during input snapshot')
            task['path'] = str(snapshot)
        for index, path in enumerate(resolved.resolved_facts.get('agent_option_paths', [])):
            target = native['agents'][0]['kwargs']
            for key in path[:-1]:
                target = target[key]
            source = Path(target[path[-1]])
            snapshot = inputs_root / 'agent-inputs' / str(index) / source.name
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, snapshot)
                digest = tree_digest(snapshot)
            else:
                shutil.copyfile(source, snapshot)
                digest = sha256_file(snapshot)
            if digest != resolved.resolved_facts['identity_facts']['agent_option_content']['.'.join(path)]:
                raise RequestValidationError('Harbor agent file input changed during snapshot')
            target[path[-1]] = str(snapshot)
        endpoint = context.model_endpoints.get('primary') or resolved.request.primary_model.provider_options.get('base_url')
        with contextlib.ExitStack() as stack:
            if endpoint:
                if resolved.resolved_facts.get('endpoint_location') == 'sandbox':
                    compose, endpoint = stack.enter_context(endpoint_bridge(inputs_root / 'bridge', endpoint))
                    native['environment']['extra_docker_compose'] = [str(compose)]
                    native['agents'][0]['extra_allowed_hosts'] = ['model-relay']
                native['agents'][0]['env'] = {'OPENAI_API_BASE': endpoint, 'OPENAI_BASE_URL': endpoint,
                    **({'OPENAI_API_KEY': os.environ['OPENAI_API_KEY']} if os.environ.get('OPENAI_API_KEY') else {})}
            native.update(job_name=job_name, jobs_dir=str(root))
            config = JobConfig.model_validate(native)
            job_dir = root / job_name
            forced_status = failure = None
            try:
                job = await Job.create(config)
                async def record_environment(event):
                    # This public event precedes sandbox creation at the pin.
                    # Commit ownership before any Docker resources can appear.
                    record_project(context.output_dir, event.trial_name)
                    if environment_started_hook is not None:
                        await environment_started_hook(event)

                job.on_environment_started(record_environment)
                if agent_started_hook is not None:
                    job.on_agent_started(agent_started_hook)
                await job.run()
            except asyncio.CancelledError:
                forced_status = 'cancelled'
            except Exception as exc:
                forced_status, failure = 'failed', f'{type(exc).__name__}: {exc}'
            if not (job_dir / 'result.json').is_file():
                raise ArtifactError(f'Harbor did not publish a native job result: {failure or forced_status}')
            return normalize_harbor_job(job_dir, identity=resolved.identity, fallback_task=resolved.request.task,
                location_prefix='native/harbor/' + job_name, forced_status=forced_status, failure=failure)

    async def cleanup_worker_resources(self, work_dir: Path):
        return await asyncio.to_thread(cleanup_owned_docker, work_dir)

    def import_results(self, resolved: ResolvedEvaluation, source: str, context: ExecutionContext):
        protocol = _execution_protocol(resolved.request)
        if protocol is not None:
            return protocol.import_results(self, resolved, Path(source))
        del context
        result = normalize_harbor_job(Path(source), identity=resolved.identity, fallback_task=resolved.request.task)
        self.validate_import_facts(resolved, result)
        return result

    def validate_import_facts(self, resolved, result):
        """Observed native selection/model checks shared with paired protocols."""
        identity_facts = resolved.resolved_facts.get('identity_facts', {})
        expected_tasks = set(identity_facts.get('native_task_names', identity_facts.get('selected_tasks', [])))
        if expected_tasks and {s.sample_id for s in result.samples} - expected_tasks:
            raise ArtifactError('Harbor imported trials do not match the selected task ids')
        qualified = resolved.native_config.get('agents', [{}])[0].get('model_name')
        provider, separator, model = str(qualified or '').partition('/')
        expected = (model, provider) if separator else (provider, None)
        for sample in result.samples:
            model_info = (sample.native.get('agent_info') or {}).get('model_info')
            if model_info and (model_info.get('name'), model_info.get('provider')) != expected:
                raise ArtifactError('Harbor imported native model does not match the resolved request')
