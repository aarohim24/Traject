"""Unit tests for traject.compression.strategies."""

from __future__ import annotations

import pytest

from traject.compression.strategies import (
    STRATEGY_DEFAULTS,
    CompressionConfig,
    CompressionStrategy,
    get_config,
    validate_config,
)
from traject.exceptions import TrajectConfigError


class TestCompressionStrategy:
    def test_three_members(self) -> None:
        assert len(CompressionStrategy) == 3

    def test_conservative_value(self) -> None:
        assert CompressionStrategy.CONSERVATIVE == "conservative"

    def test_str_subclass(self) -> None:
        assert isinstance(CompressionStrategy.MODERATE, str)


class TestStrategyDefaults:
    def test_all_strategies_present(self) -> None:
        for s in CompressionStrategy:
            assert s in STRATEGY_DEFAULTS

    def test_conservative_target(self) -> None:
        assert (
            STRATEGY_DEFAULTS[CompressionStrategy.CONSERVATIVE].target_reduction_pct
            == 0.20
        )

    def test_moderate_target(self) -> None:
        assert (
            STRATEGY_DEFAULTS[CompressionStrategy.MODERATE].target_reduction_pct == 0.35
        )

    def test_aggressive_target(self) -> None:
        assert (
            STRATEGY_DEFAULTS[CompressionStrategy.AGGRESSIVE].target_reduction_pct
            == 0.55
        )

    def test_conservative_min_turns(self) -> None:
        assert (
            STRATEGY_DEFAULTS[CompressionStrategy.CONSERVATIVE].min_turns_protected == 3
        )

    def test_aggressive_min_turns(self) -> None:
        assert (
            STRATEGY_DEFAULTS[CompressionStrategy.AGGRESSIVE].min_turns_protected == 2
        )

    def test_all_default_shadow_mode_true(self) -> None:
        for config in STRATEGY_DEFAULTS.values():
            assert config.shadow_mode is True

    def test_all_default_protect_system_prompt_true(self) -> None:
        for config in STRATEGY_DEFAULTS.values():
            assert config.protect_system_prompt is True


class TestGetConfig:
    @pytest.mark.parametrize("strategy", list(CompressionStrategy))
    def test_returns_correct_strategy(self, strategy: CompressionStrategy) -> None:
        config = get_config(strategy)
        assert config.strategy == strategy

    def test_returns_frozen_config(self) -> None:
        import dataclasses

        config = get_config(CompressionStrategy.CONSERVATIVE)
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.target_reduction_pct = 0.99  # type: ignore[misc]


class TestValidateConfig:
    def _base_config(self, **kw: object) -> CompressionConfig:
        return CompressionConfig(
            strategy=CompressionStrategy.CONSERVATIVE,
            target_reduction_pct=kw.get("target_reduction_pct", 0.20),  # type: ignore[arg-type]
            min_turns_protected=kw.get("min_turns_protected", 3),  # type: ignore[arg-type]
            protect_system_prompt=kw.get("protect_system_prompt", True),  # type: ignore[arg-type]
            shadow_mode=True,
        )

    def test_valid_config_passes(self) -> None:
        validate_config(self._base_config())  # should not raise

    def test_target_0_raises(self) -> None:
        with pytest.raises(TrajectConfigError):
            validate_config(self._base_config(target_reduction_pct=0.0))

    def test_target_1_raises(self) -> None:
        with pytest.raises(TrajectConfigError):
            validate_config(self._base_config(target_reduction_pct=1.0))

    def test_target_negative_raises(self) -> None:
        with pytest.raises(TrajectConfigError):
            validate_config(self._base_config(target_reduction_pct=-0.1))

    def test_target_above_1_raises(self) -> None:
        with pytest.raises(TrajectConfigError):
            validate_config(self._base_config(target_reduction_pct=1.1))

    def test_min_turns_negative_raises(self) -> None:
        with pytest.raises(TrajectConfigError):
            validate_config(self._base_config(min_turns_protected=-1))

    def test_protect_system_prompt_false_raises(self) -> None:
        with pytest.raises(TrajectConfigError):
            validate_config(self._base_config(protect_system_prompt=False))
