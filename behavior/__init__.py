# 零 · 行为控制层
# 向后兼容——从子模块重导出所有符号

from behavior.control import (
    compute_control_strength, estimate_uncertainty,
)
from behavior.profiles import (
    SchemaMode, TempPolicy, temperature_policy, schema_mode,
    validate_output, BehaviorProfile, PROFILES,
)
from behavior.canonical import (
    canonicalize, build_system, BehaviorContext, classify, seed,
    get_profile, get_temperature, list_profiles,
)
from behavior.calibration import (
    ControlMemory, ControlRecord, calibrated_strength,
    record_outcome, record_feedback, get_control_memory,
)
from behavior_canon import (
    synthetic_evaluate, auto_ground, _llm_evaluate,
)
from behavior.grounding import (
    GroundTruth, GroundedJudge, ExternalAnchorGate, EntropyInjector,
    ExternalSignalGateway, reality_check, drift_align,
    auto_ground_v2, auto_ground_v3, record_signal_source,
    get_anchor_penalty, inject_entropy, ingest_external,
    get_external_score, validate_reward, RewardValidation,
    JudgeRegistry, CalibratedConfidence, multi_judge,
)
