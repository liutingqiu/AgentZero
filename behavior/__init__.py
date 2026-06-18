# 零 · 行为控制层
# 行为模块已合并为 behavior_canon.py
# behavior/ 子目录文件为遗留碎片，不再使用
# 所有导出重定向到 behavior_canon

import warnings
warnings.warn(
    'behavior/ 子模块已废弃，请直接从 behavior_canon 导入',
    DeprecationWarning, stacklevel=2
)

from behavior_canon import (
    BehaviorContext,
    CalibratedConfidence,
    ControlMemory,
    ControlRecord,
    EntropyInjector,
    ExternalAnchorGate,
    ExternalSignalGateway,
    JudgeRegistry,
    Path,
    RewardValidation,
    SchemaMode,
    TempPolicy,
    auto_ground,
    auto_ground_v2,
    auto_ground_v3,
    build_system,
    calibrated_strength,
    canonicalize,
    classify,
    compute_control_strength,
    drift_align,
    estimate_uncertainty,
    get_agent_residual,
    get_anchor_penalty,
    get_control_memory,
    get_external_score,
    ingest_external,
    inject_entropy,
    multi_judge,
    reality_check,
    record_feedback,
    record_objective,
    record_outcome,
    record_signal_source,
    schema_mode,
    seed,
    select_path,
    synthetic_evaluate,
    temperature_policy,
    validate_output,
    validate_reward,
)