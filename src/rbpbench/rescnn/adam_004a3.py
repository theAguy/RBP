"""Explicit CUDA Adam semantics and the three-step Task 004A-3 oracle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import torch

from rbpbench.rescnn.config import EXPECTED_OPTIMIZER, Task004AConfig, validate_config_object


ADAM_FLAGS = {
    "foreach": True,
    "fused": False,
    "capturable": False,
    "differentiable": False,
    "maximize": False,
}
ORACLE_RTOL = 1e-6
ORACLE_ATOL = 1e-7
ORACLE_STEPS = 3


class ResCNN004A3AdamError(RuntimeError):
    pass


def build_gpu_adam(
    model: torch.nn.Module,
    config: Task004AConfig,
    *,
    foreach: bool = True,
) -> torch.optim.Adam:
    validate_config_object(config)
    if dict(config.optimizer) != EXPECTED_OPTIMIZER:
        raise ResCNN004A3AdamError("optimizer values differ from frozen constants")
    values = config.optimizer
    optimizer = torch.optim.Adam(
        model.parameters(), lr=float(values["learning_rate"]),
        betas=tuple(float(v) for v in values["betas"]),
        eps=float(values["epsilon"]), weight_decay=float(values["weight_decay"]),
        amsgrad=bool(values["amsgrad"]), foreach=foreach, fused=False,
        capturable=False, differentiable=False, maximize=False,
    )
    group = optimizer.param_groups[0]
    expected = {**ADAM_FLAGS, "foreach": foreach}
    for key, value in expected.items():
        if group.get(key) is not value:
            raise ResCNN004A3AdamError(f"effective Adam flag drift: {key}={group.get(key)!r}")
    return optimizer


@dataclass(frozen=True)
class AdamOracleEvidence:
    steps: int
    rtol: float
    atol: float
    device: str
    compared_parameters: int
    compared_state_tensors: int
    step_counters_equal: bool


def _state_for(optimizer: torch.optim.Optimizer, parameter: torch.Tensor) -> Mapping[str, object]:
    state = optimizer.state.get(parameter)
    if not state:
        raise ResCNN004A3AdamError("Adam state was not created")
    return state


def run_three_step_oracle(
    config: Task004AConfig,
    *,
    device: str | torch.device = "cpu",
) -> AdamOracleEvidence:
    """Compare foreach Adam with the single-tensor reference over three steps."""

    device = torch.device(device)
    torch.manual_seed(44003)
    left = torch.nn.Sequential(torch.nn.Linear(7, 5), torch.nn.Linear(5, 3)).to(device)
    right = torch.nn.Sequential(torch.nn.Linear(7, 5), torch.nn.Linear(5, 3)).to(device)
    right.load_state_dict(left.state_dict())
    foreach = build_gpu_adam(left, config, foreach=True)
    reference = build_gpu_adam(right, config, foreach=False)
    compared_states = 0
    for step in range(ORACLE_STEPS):
        generator = torch.Generator(device=device.type)
        generator.manual_seed(91_000 + step)
        inputs = torch.randn((11, 7), dtype=torch.float32, device=device, generator=generator)
        targets = torch.randn((11, 3), dtype=torch.float32, device=device, generator=generator)
        left_loss = torch.nn.functional.mse_loss(left(inputs), targets)
        right_loss = torch.nn.functional.mse_loss(right(inputs), targets)
        if not torch.equal(left_loss, right_loss):
            raise ResCNN004A3AdamError("oracle pre-update losses differ")
        left_loss.backward()
        right_loss.backward()
        for left_parameter, right_parameter in zip(left.parameters(), right.parameters()):
            if not torch.equal(left_parameter.grad, right_parameter.grad):
                raise ResCNN004A3AdamError("oracle pre-update gradients differ")
        foreach.step()
        reference.step()
        foreach.zero_grad(set_to_none=True)
        reference.zero_grad(set_to_none=True)

    for left_parameter, right_parameter in zip(left.parameters(), right.parameters()):
        torch.testing.assert_close(
            left_parameter, right_parameter, rtol=ORACLE_RTOL, atol=ORACLE_ATOL,
        )
        left_state = _state_for(foreach, left_parameter)
        right_state = _state_for(reference, right_parameter)
        for key in ("exp_avg", "exp_avg_sq"):
            torch.testing.assert_close(
                left_state[key], right_state[key], rtol=ORACLE_RTOL, atol=ORACLE_ATOL,
            )
            compared_states += 1
        if int(left_state["step"].item()) != int(right_state["step"].item()):
            raise ResCNN004A3AdamError("Adam step counters differ")
        if int(left_state["step"].item()) != ORACLE_STEPS:
            raise ResCNN004A3AdamError("Adam oracle did not execute exactly three steps")
    return AdamOracleEvidence(
        steps=ORACLE_STEPS, rtol=ORACLE_RTOL, atol=ORACLE_ATOL,
        device=str(device), compared_parameters=sum(1 for _ in left.parameters()),
        compared_state_tensors=compared_states, step_counters_equal=True,
    )
