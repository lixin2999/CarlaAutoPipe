"""CARLA 车辆与地图资产自动化导入工具系统 —— CLI 核心包。

所有业务逻辑唯一实现在本包（CLI）与 UE Commandlet 中，GUI 仅作为薄壳
通过 subprocess 调用 CLI 并解析 JSON 报告（严格遵循详细设计 V1.4 §5.2）。
"""

__version__ = "1.0.0"
