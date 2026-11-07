"""全局常量：统一退出码契约、错误等级、标准骨架定义、资产路径常量。

退出码契约为 CLI / Commandlet / CI / GUI 四方的稳定契约（详细设计 V1.4 §5.1），
任何模块不得私自扩展或改变语义。
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """统一退出码契约（V1.4 §5.1）。"""

    SUCCESS = 0                    # 执行成功，CI/GUI 正常推进
    ASSET_VALIDATION_FAIL = 1      # Manifest 或资产校验失败，GUI 解析 JSON 渲染错误卡片
    ENGINE_INTERNAL_ERROR = 2      # UE 进程崩溃或 Commandlet 运行时异常
    ENVIRONMENT_ERROR = 3          # 前置环境缺失：无 Blender / 路径错误 / 黄金模板哈希校验不匹配


class Level:
    """校验错误等级（V1.2 §4.1 错误分级）。"""

    ERROR = "ERROR"        # 致命：阻断后续流程
    WARNING = "WARNING"    # 严重：可执行但高概率运行异常，输出修改建议
    INFO = "INFO"          # 优化提示：不影响运行


# ---------------------------------------------------------------------------
# CARLA 标准五骨骨架（绝对红线：名称、层级、旋转缩放严禁修改，仅允许平移微调）
# ---------------------------------------------------------------------------
SKELETON_ROOT_BONE = "Vehicle_Bone_Root"
SKELETON_BASE_BONE = "Vehicle_Base"
SKELETON_WHEEL_BONES = ("FL_Wheel", "FR_Wheel", "RL_Wheel", "RR_Wheel")
SKELETON_ALL_BONES = (SKELETON_ROOT_BONE, SKELETON_BASE_BONE) + SKELETON_WHEEL_BONES

# 车轮象限顺序（Blender 侧聚类识别后按此排序：FL 左前 / FR 右前 / RL 左后 / RR 右后）
WHEEL_QUADRANT_ORDER = ("FL_Wheel", "FR_Wheel", "RL_Wheel", "RR_Wheel")

# 车轮几何聚类特征阈值（V1.2 §4.1：盘状度 X≈Z≫Y + 体积占比 0.8%~5%）
WHEEL_VOLUME_RATIO_MIN = 0.008
WHEEL_VOLUME_RATIO_MAX = 0.05
WHEEL_DISKNESS_Y_RATIO = 0.4   # Y 轴（厚度）与 X/Z 均值的比低于该值视为盘状

# ---------------------------------------------------------------------------
# UE 资产路径常量（构建端）
# ---------------------------------------------------------------------------
GAME_ROOT = "/Game/Carla"
VEHICLE_TEMPLATE_DIR = GAME_ROOT + "/Blueprints/Vehicles/_Template"
VEHICLE_FACTORY_PATH = GAME_ROOT + "/Blueprints/Vehicles/VehicleFactory.VehicleFactory"
VEHICLE_BLUEPRINT_DIR = GAME_ROOT + "/Blueprints/Vehicles"          # BP_<Model>/
MAP_CONTENT_DIR = GAME_ROOT + "/Maps"
BLUEPRINT_PARENT = "BaseVehiclePawn"   # 红线：车辆蓝图父类

# FVehicleParameters 字段（CARLA 0.9.16 源码已确认，V1.2 §4.5 通道 A）
VEHICLE_PARAMETERS_FIELDS = (
    "Make", "Model", "Class", "Generation",
    "NumberOfWheels", "BaseType", "Colors",
    "HasDynamicDoors", "HasLights",
)

# ---------------------------------------------------------------------------
# 命名规范（V1.2 附录）
# ---------------------------------------------------------------------------
NAMING_PATTERNS = {
    "body_material": "M_CarBody_{model}",
    "texture": "T_CarPart_{model}_{type}",
    "vehicle_bp": "BP_{model}",
    "anim_bp": "AnimBP_{model}",
    "front_wheel_bp": "{model}_FrontWheel",
    "rear_wheel_bp": "{model}_RearWheel",
    "physics_asset": "{model}_PhysicsAsset",
    "blueprint_dir": VEHICLE_BLUEPRINT_DIR + "/{model}/",
}

# ---------------------------------------------------------------------------
# 报告文件名 / CLI 常量
# ---------------------------------------------------------------------------
REPORT_SCHEMA_VERSION = "1.0"
COMMAND_NAMES = (
    "validate", "rig", "build-vehicle", "build-map",
    "pack", "inject", "smoke",
)

# Commandlet 名称（UE 侧注册名，-run=CarlaAssetImport）
COMMANDLET_NAME = "CarlaAssetImport"
