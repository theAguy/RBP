"""Literal 500-nt architecture from the former teammate's notebook cell 8."""

from __future__ import annotations

import torch
import torch.nn as nn


EXPECTED_WINDOW = 500
EXPECTED_OUTPUTS = 122
EXPECTED_LEARNABLE_PARAMETERS = 9_029_562


class ResidualBlock1D(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=3, pool=True):
        super().__init__()
        self.pool = pool
        self.same_channels = in_channels == out_channels

        self.conv1 = nn.Conv1d(
            in_channels,
            out_channels,
            kernel_size=kernel_size,
            stride=1,
            padding=kernel_size // 2,
            dilation=1,
            groups=1,
            bias=True,
            padding_mode="zeros",
        )
        self.bn1 = nn.BatchNorm1d(
            out_channels, eps=1e-5, momentum=0.1, affine=True, track_running_stats=True,
        )
        self.relu = nn.ReLU(inplace=False)

        self.conv2 = nn.Conv1d(
            out_channels,
            out_channels,
            kernel_size=kernel_size,
            stride=1,
            padding=kernel_size // 2,
            dilation=1,
            groups=1,
            bias=True,
            padding_mode="zeros",
        )
        self.bn2 = nn.BatchNorm1d(
            out_channels, eps=1e-5, momentum=0.1, affine=True, track_running_stats=True,
        )

        if not self.same_channels:
            self.residual = nn.Conv1d(
                in_channels,
                out_channels,
                kernel_size=1,
                stride=1,
                padding=0,
                dilation=1,
                groups=1,
                bias=True,
                padding_mode="zeros",
            )
        else:
            self.residual = nn.Identity()

        self.pool_layer = (
            nn.MaxPool1d(
                kernel_size=2,
                stride=2,
                padding=0,
                dilation=1,
                return_indices=False,
                ceil_mode=False,
            )
            if pool
            else nn.Identity()
        )

    def forward(self, x):
        identity = self.residual(x)
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        out += identity
        out = self.relu(out)
        out = self.pool_layer(out)
        return out


class CNNMultiLabelResidual(nn.Module):
    def __init__(self, num_labels=EXPECTED_OUTPUTS):
        super().__init__()
        self.encoder = nn.Sequential(
            ResidualBlock1D(4, 64, kernel_size=7, pool=True),
            ResidualBlock1D(64, 128, kernel_size=7, pool=True),
            ResidualBlock1D(128, 256, kernel_size=5, pool=True),
        )
        self.classifier = nn.Sequential(
            nn.Linear(256 * 62, 512, bias=True),
            nn.BatchNorm1d(512, eps=1e-5, momentum=0.1, affine=True, track_running_stats=True),
            nn.ReLU(inplace=False),
            nn.Dropout(p=0.4, inplace=False),
            nn.Linear(512, 256, bias=True),
            nn.BatchNorm1d(256, eps=1e-5, momentum=0.1, affine=True, track_running_stats=True),
            nn.ReLU(inplace=False),
            nn.Dropout(p=0.3, inplace=False),
            nn.Linear(256, num_labels, bias=True),
        )

    def forward(self, x):
        if x.ndim != 3 or tuple(x.shape[1:]) != (EXPECTED_WINDOW, 4):
            raise ValueError(f"expected input [batch,{EXPECTED_WINDOW},4], got {tuple(x.shape)}")
        x = x.permute(0, 2, 1)
        x = self.encoder(x)
        x = x.view(x.size(0), -1)
        return self.classifier(x)


def count_learnable_parameters(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
