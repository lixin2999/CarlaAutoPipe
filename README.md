# CARLA 车辆与地图资产自动化导入工具（carla-asset-pipeline）

**版本：V1.0.0** ｜ 适用 CARLA **0.9.16**（UE 4.26）｜ 依据《CARLA 车辆与地图资产自动化导入工具系统详细设计文档 V1.4》实现

一套面向仿真资产团队的端到端工具链：将第三方车辆 / 地图资产从 **原始 FBX** 一路自动化推进到
**可注入 Release 版 CARLA 的标准资产包**，覆盖前置校验、自动绑骨、UE 引擎导入与工厂注册、
平台差异化打包、幂等注入与冒烟回归，并提供 PyQt5 GUI 薄壳与 CI 流水线集成。

---

## 特性一览

| 能力 | 说明 |
| --- | --- |
| **校验左移** | Blender 后台 L1 合规检查（单位 cm / +X 车头 / +Z 天 / 车轮分件 / 五骨骨架 / 原点接地），杜绝返工进入引擎环节 |
| **自动绑骨** | 刚性绑定到 CARLA 标准五骨骨架（`Vehicle_Bone_Root → Vehicle_Base → FL/FR/RL/RR_Wheel`），名称/层级/旋转缩放绝不触碰 |
| **引擎导入 Commandlet** | UE 4.26 C++ 插件 `CarlaAssetImport`：FBX 固化参数导入 → 物理资产构建 → 黄金模板复制 → VehicleFactory 双通道注册 |
| **黄金模板哈希绝对卡点** | 复制前校验模板目录 SHA-256（Python/C++ 双端同算法），模板被篡改即刻阻断（退出码 3） |
| **延迟编译事务队列** | 批量注册仅注入 CDO，批处理末尾统一 `CompileBlueprint + Save`，避免逐资产编译风暴 |
| **NavMesh 异步等待** | 流式加载 + 物理就绪轮询后，先车辆层后行人层两阶段重建，杜绝半初始化重建失败 |
| **平台差异化打包** | Windows → zip；Linux → tar.gz（官方 ImportAssets.sh 通路）；可选 pak；Manifest 随包归档可追溯 |
| **幂等注入 + 快照回滚** | 指纹一致自动跳过；覆盖前快照备份，失败一键回滚；★全路径 POSIX 正斜杠归一化 |
| **冒烟回归** | 车辆八项 / 地图六项自动化断言，单项失败即整体 FAIL，产出 JUnit XML 供 CI 归档 |
| **GUI 薄壳** | PyQt5 步骤导航 + 流式日志 + 诊断卡片（级别/描述/修复建议/点击跳转），仅解析 JSON 报告，零业务逻辑 |

## 架构总览

```
                        ┌──────────────────────────────────────────┐
 原始 FBX / XODR ──────▶│ CLI carla-asset（唯一业务逻辑载体）        │◀────── PyQt5 GUI 薄壳
                        │  validate → rig → build-* → pack →       │        （subprocess + JSON 报告）
                        │  inject → smoke                          │
                        └──────┬──────────┬──────────┬─────────────┘
                               │          │          │
                     Blender 后台    UE4Editor-Cmd   CARLA Python API
                     (bpy 脚本)     (CarlaAssetImport (smoke 八项/六项)
                                     Commandlet C++)
```

统一退出码契约（CLI / Commandlet / CI / GUI 四方稳定约定）：

| 码 | 含义 | 处置 |
| --- | --- | --- |
| `0` | SUCCESS | 正常推进 |
| `1` | ASSET_VALIDATION_FAIL | 资产/清单不合规，GUI 渲染错误卡片 |
| `2` | ENGINE_INTERNAL_ERROR | UE/Blender 进程崩溃或内部异常 |
| `3` | ENVIRONMENT_ERROR | 前置环境缺失 / 黄金模板哈希不匹配 |

## 安装

```bash
# Python 3.8+
pip install -r requirements.txt
pip install -e .                # 提供 carla-asset / carla-asset-gui 控制台入口

# 环境接线（Blender / UE4.26 / CARLA / 黄金模板均为外部依赖，路径可配置）
copy configs\settings.example.json configs\settings.json   # 按本机实际路径修改
```

依赖检测缺失时所有命令返回退出码 `3` 并附修复指引，可先运行 `carla-asset doctor` 自检。

## 快速开始（车辆轨）

```bash
# 1. 前置校验原始 FBX（Blender 后台）
carla-asset validate --type vehicle --input raw/vehicles/su7.fbx

# 2. 自动绑骨 + 导出合规 FBX
carla-asset rig --fbx raw/vehicles/su7.fbx --out out/vehicles/su7_rigged.fbx

# 3. 编写 manifests/vehicles/su7.json（对照 schemas/vehicle.schema.json），引擎导入+注册
carla-asset build-vehicle --manifest manifests/vehicles/su7.json

# 4. 平台打包
carla-asset pack --pkg su7 --src Dist/Staged/Content/Carla --manifest manifests/vehicles/su7.json --platform win

# 5. 注入 Release 版 CARLA（自动快照备份，失败可回滚）
carla-asset inject --pkg Dist/su7.zip --rollback-on-fail

# 6. 冒烟八项回归
carla-asset smoke --type vehicle --name xiaomi.su7
```

GUI：`carla-asset-gui` —— 按左侧步骤树 1→7 顺序执行即可。

## CLI 命令一览

| 命令 | 职责 | 关键参数 |
| --- | --- | --- |
| `validate` | Blender 前置合规校验 | `--type vehicle\|map --input <fbx> [--xodr] [--manifest]` |
| `rig` | 自动绑骨并导出合规 FBX | `--fbx <in> --out <out> [--mirror-y]` |
| `build-vehicle` | UE 侧车辆构建+工厂注册 | `--manifest <json> [--dry-run] [--skip-factory] [--batch-size N]` |
| `build-map` | UE 侧地图导入+NavMesh | `--manifest <json> [--dry-run] [--skip-navmesh] [--batch-size N]` |
| `pack` | 平台差异化打包 | `--pkg <名> --src <目录> [--manifest] [--platform win\|linux] [--format zip\|pak]` |
| `inject` | Release 版幂等注入 | `--pkg <包> [--carla-root] [--rollback-on-fail] [--force]` |
| `smoke` | 冒烟自动化回归 | `--type vehicle\|map --name <名> [--batch <目录>] [--host] [--port]` |
| `doctor` | 环境自检 | — |

全部子命令支持 `--report <file.json>`（GUI/CI 消费的结构化诊断报告）；`--dry-run` 只校验不落地。

## 仓库结构

```
├── pyproject.toml / setup.py / requirements.txt
├── configs/settings.example.json     # 外部依赖路径模板
├── schemas/                          # Manifest JSON Schema（强校验）
├── manifests/                        # 车辆/地图资产清单样例
├── carla_asset/                      # CLI 核心 Python 包
├── blender_scripts/                  # Blender 后台脚本（校验/绑骨）
├── plugin/CarlaAssetImporter/        # UE 4.26 C++ 插件源码（目标机编译）
├── gui/                              # PyQt5 GUI 薄壳
├── ci/pipeline.yml                   # 四 Stage 流水线
├── tests/                            # pytest 单元测试
└── docs/                             # 用户手册/部署/技术规范/RELEASE
```

## 文档索引

- [用户手册](docs/USER_MANUAL.md) —— 资产准备规范、分轨操作指引、逐命令示例、GUI 指南
- [部署指南](docs/DEPLOYMENT.md) —— 构建端/运行端/CI Agent 部署与 C++ 插件编译验证清单
- [发布说明](docs/RELEASE.md) —— 版本历史（V1.0.0 起）
- [资产导入技术规范](docs/IMPORT_SPEC.md) —— 坐标/骨架/命名/物理/模板硬性要求
- [注入与发布规范](docs/INJECT_RELEASE.md) —— 打包格式、注入通路、回滚流程
- [常见问题排查](docs/TROUBLESHOOTING.md) —— 错误码对照与修复手册

## 版本规则

初始版本 **V1.0.0**。此后：功能新增/变更 → 第二位（次版本号）递增；问题修复/功能完善 →
第三位（修订号）递增。每次迭代在 [docs/RELEASE.md](docs/RELEASE.md) 顶部新增条目，不删除历史。

## License / 合规

内部仿真用途。第三方商用资产再分发前需单独确认授权（详见设计文档风险清单）。
