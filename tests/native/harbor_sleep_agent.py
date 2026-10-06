"""Native cancellation fixture with an observable running sandbox command."""
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
        await environment.exec(command="sleep 90", timeout_sec=100)
