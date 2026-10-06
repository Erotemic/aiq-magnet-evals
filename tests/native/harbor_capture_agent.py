"""Acceptance-only oracle/NOP wrapper with unchanged upstream patch capture."""
import json
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.agents.oracle import OracleAgent
from harbor.models.trial.paths import TrialPaths


class CaptureAgent(BaseAgent):
    def __init__(self, *args, mode='oracle', **kwargs):
        super().__init__(*args, **kwargs)
        if mode not in ('oracle', 'nop'):
            raise ValueError('acceptance mode must be oracle or nop')
        self.mode = mode

    @staticmethod
    def name():
        return 'acceptance-oracle-nop-capture'

    def version(self):
        return '1.0.0'

    async def setup(self, environment):
        pass

    async def run(self, instruction, environment, context):
        config = json.loads((self.logs_dir.parent / 'config.json').read_text())
        if self.mode == 'oracle':
            oracle = OracleAgent(logs_dir=self.logs_dir, task_dir=Path(config['task']['path']),
                                 trial_paths=TrialPaths(self.logs_dir.parent),
                                 model_name=config['agent']['model_name'])
            await oracle.run(instruction, environment, context)
        from locked_mini_swe import _CAPTURE
        result = await environment.exec(command=_CAPTURE, user='root', timeout_sec=300)
        if result.return_code:
            raise RuntimeError('native patch capture command failed')
