"""Fail in an actual Harbor agent phase to verify failed-attempt publication."""
from tests.native.harbor_sleep_agent import SleepAgent


class FailureAgent(SleepAgent):
    @staticmethod
    def name():
        return 'aiq-harbor-failure-fixture'

    async def run(self, instruction, environment, context):
        raise RuntimeError('intentional native Harbor agent exception')
