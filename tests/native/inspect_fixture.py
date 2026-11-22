"""Deterministic local provider and tasks for native Inspect acceptance runs.

The model is deliberately local; Inspect still performs its actual evaluation,
tool dispatch, scoring, epoch reduction, and log serialization.
"""

import asyncio
import os
import subprocess

from inspect_ai import Epochs, Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelAPI, ModelOutput, get_model, modelapi
from inspect_ai.scorer import includes, match
from inspect_ai.solver import generate, solver, use_tools
from inspect_ai.tool import tool


@modelapi(name="fixture")
class FixtureModel(ModelAPI):
    async def generate(self, input, tools, tool_choice, config):
        del tool_choice, config
        if self.model_name == "broken":
            raise RuntimeError("judge model failure")
        if self.model_name == "slow":
            child = subprocess.Popen(["sleep", "120"])
            with open(os.environ["AIQ_P1_CHILD_PID_FILE"], "w") as file:
                file.write(str(child.pid))
            await asyncio.sleep(120)
        if tools and not any(message.role == "tool" for message in input):
            return ModelOutput.for_tool_call(
                model=self.model_name,
                tool_name=tools[0].name,
                tool_arguments={"value": 2},
            )
        return ModelOutput.from_content(model=self.model_name, content="4")


@tool
def double():
    async def execute(value: int) -> str:
        """Double an integer value.

        Args:
            value: Integer to double.
        """
        return str(value * 2)

    return execute


@task
def generation():
    return Task(
        dataset=[Sample(input="Two plus two?", target="4")],
        solver=generate(),
        scorer=[match(), includes()],
    )


@task
def tool_task():
    return Task(
        dataset=[Sample(input="Use double on two.", target="4")],
        solver=[use_tools(double()), generate()],
        scorer=match(),
    )


@task
def proxy_context_task():
    """Exercise the upstream ReAct context-stop path before ordinary scoring."""
    from inspect_ai.agent import react

    return Task(
        dataset=[Sample(input="Use double on two.", target="4")],
        solver=react(tools=[double()]),
        scorer=match(),
    )


@solver
def auxiliary_probe():
    async def solve(state, generate):
        del generate
        output = await get_model(role="grader", required=True).generate("Say 4")
        state.metadata["grader_output"] = output.completion
        return state

    return solve


@task
def role_task():
    return Task(
        dataset=[Sample(input="Two plus two?", target="4")],
        solver=[auxiliary_probe(), generate()],
        scorer=match(),
        epochs=Epochs(2, reducer=["mean", "mode"]),
    )
