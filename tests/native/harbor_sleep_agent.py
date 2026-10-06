"""Native cancellation fixture with an observable running sandbox command."""
import os
import signal
import subprocess
from pathlib import Path

from harbor.agents.base import BaseAgent


class SleepAgent(BaseAgent):
    @staticmethod
    def name():
        return "aiq-harbor-cancel-probe"

    def version(self):
        return "1"

    async def setup(self, environment):
        pass

    async def run(self, instruction, environment, context):
        (self.logs_dir / "started").write_text("running\n")
        child = None
        if os.environ.get('AIQ_HARBOR_CHILD_PID_FILE'):
            child = subprocess.Popen(['sleep', '120'])
            Path(os.environ['AIQ_HARBOR_CHILD_PID_FILE']).write_text(str(child.pid))
        try:
            await environment.exec(command="sleep 90", timeout_sec=100)
        finally:
            if child and child.poll() is None:
                child.terminate()
                child.wait(timeout=5)


class StubbornSleepAgent(SleepAgent):
    """Force the parent's escalation path instead of native SIGINT cleanup."""

    async def run(self, instruction, environment, context):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        await super().run(instruction, environment, context)
