"""Native fixture proving explicit file configuration controls agent behavior."""
import json
import shlex
from pathlib import Path

from harbor.agents.base import BaseAgent


class ConfigAgent(BaseAgent):
    def __init__(self, *args, config_file, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = json.loads(Path(config_file).read_text())

    @staticmethod
    def name():
        return 'aiq-config-fixture'

    def version(self):
        return '1'

    async def setup(self, environment):
        return

    async def run(self, instruction, environment, context):
        (self.logs_dir / 'consumed-config.json').write_text(json.dumps(self.config))
        if self.config['solve']:
            code = "from pathlib import Path; Path('/app/calc.py').write_text(" + repr(
                'def divide(numerator, denominator):\n    if denominator == 0:\n'
                '        raise ValueError("zero denominator")\n    return numerator / denominator\n') + ')'
            result = await environment.exec(command='python -c ' + shlex.quote(code))
            if result.return_code:
                raise RuntimeError(result.stderr)
