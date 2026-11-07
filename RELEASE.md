# 发布说明（CHANGELOG）

> **版本递增规则（自 V1.0.0 起长期生效，文件头固化）**
>
> - 版本号格式 `V<major>.<minor>.<patch>`：
>   - **功能新增 / 功能变更** → 第二位 `<minor>` 递增（patch 归零）；
>   - **问题修复 / 功能完善** → 第三位 `<patch>` 递增；
>   - 破坏性契约变更（退出码语义、Manifest Schema 不兼容改动）→ 第一位 `<major>` 递增，需单独评审。
> - 每次迭代在本文件**顶部新增**一个版本条目，**永不删除历史条目**；
> - 条目分类标记：`新增` / `变更` / `修复` / `完善` / `已知限制`。

---

## V1.0.0 — 2026-11-07（首个正式版本）

依据《CARLA 车辆与地图资产自动化导入工具系统详细设计文档 V1.4》完成全量功能交付。

### 新增

- **CLI 工具链 `carla-asset`（唯一业务逻辑载体）**，七个子命令 + `doctor` 环境自检：
  - `validate`：Blender 后台 L1 前置资产合规校验（错误左移）；
  - `rig`：自动绑骨到 CARLA 标准五骨骨架并导出合规 FBX（检查 → 修复 → 回读验证三段式，支持 `--mirror-y`）；
  - `build-vehicle` / `build-map`：拉起 UE4Editor-Cmd 执行 `CarlaAssetImport` Commandlet，
    支持 `--dry-run` / `--skip-factory` / `--skip-navmesh` / `--batch-size`；
  - `pack`：平台差异化打包（win→zip、linux→tar.gz、可选 pak 委托 UnrealPak），Manifest 随包归档；
  - `inject`：Release 版幂等注入（目录结构自动探测、指纹跳过、快照备份、`--rollback-on-fail` 自动回滚）；
  - `smoke`：注入后冒烟回归（车辆八项 / 地图六项，`--batch` 批量模式，产出 JUnit XML）。
- **统一退出码契约**：`0` SUCCESS / `1` ASSET_VALIDATION_FAIL / `2` ENGINE_INTERNAL_ERROR /
  `3` ENVIRONMENT_ERROR；统一 JSON 诊断报告模型（level/code/message/suggestion/file/line），
  全部子命令支持 `--report`。
- **UE 4.26 C++ 插件 `CarlaAssetImporter`**（源码交付，目标机编译）：
  - `CarlaAssetImportCommandlet`：vehicle/map 双模式编排，批末统一 GC 与事务 Flush；
  - `TemplateHashGuard`：★黄金模板 SHA-256 绝对卡点（内嵌 FIPS 180-4 实现，与 Python 端 `checksum.py` 同算法）；
  - `FbxImporter`：固化导入参数（单位 cm、+X Forward、-Z 转换、不导入叶骨骼）；
  - `GoldenTemplateCopier`：`IAssetTools::Duplicate` 复制模板 + 引用改写 Visitor；
  - `VehiclePhysicsBuilder`：清默认胶囊 → 车身 SingleConvexHull → 车轮 Sphere/Kinematic/HitEvents → 约束断言；
  - `VehicleBlueprintAssembler`：映射表改写（SkelMesh/PhysicsAsset/AnimBP/前后轮 BP/VehicleBP），父类强制 `BaseVehiclePawn`；
  - `VehicleFactoryRegistrar`：★通道 A 双注册 + CDO Vehicles 数组幂等追加 + 延迟编译事务队列（批末统一
    `CompileBlueprint + MarkDirty + Save`）；`--skip-factory` 走通道 B 降级按路径加载；
  - `MapImporter`：FBX 导入 → XODR 路网绑定 → 材质适配（可关）→ ★NavMesh 两阶段生成
    （FStreamableManager 异步等待碰撞与 Actor 就绪后先车辆层后行人层 Rebuild）→ 关卡清单注册。
- **Blender 脚本**：`validate_mesh.py`（单位/轴向/车轮分件/骨架/原点接地/非等比缩放 ERROR 级，
  车轮盘状度+体积占比聚类识别与象限排序，地图 FBX↔XODR 一致性）、`rig_and_validate.py`（刚性权重 1.0，
  禁包络/平滑，导出参数固化）。
- **PyQt5 GUI 薄壳 `carla-asset-gui`**：步骤导航树（绿/红状态）+ 流式日志关键字高亮 + 诊断卡片
  （点击跳转关联文件）+ 启动环境自检禁用缺失步骤 + 注入/覆盖/回滚前差异清单二次确认；
  仅通过 subprocess 调 CLI 并解析 JSON 报告，零业务逻辑。
- **Manifest 契约层**：`schemas/vehicle.schema.json` / `map.schema.json` 强校验、
  make/model 强制小写归一化、交叉一致性（蓝图父类红线、wheels∈{2,4}、XODR/FBX 同名）；
  示例清单 `manifests/vehicles/su7.json`、`manifests/maps/town10.json`。
- **CI 流水线** `ci/pipeline.yml`：四 Stage（Lint & Validate → Build Host Commandlet →
  Package → Inject + Smoke），产物与 JUnit 报告归档。
- **单元测试** `tests/`：Schema、小写归一化、模板哈希（含文档示例向量）、退出码映射、
  pack/inject 正斜杠归一、注入幂等与快照回滚（tmp_path 模拟）、报告序列化、车轮象限排序纯算法、
  CLI 参数契约。
- **跨平台路径归一化**：pack/inject 全程 `pathlib` + `as_posix()`，包内清单 JSON 同样正斜杠，
  杜绝反斜杠导致的 Asset Registry 解析失败。
- **防 OOM 机制**：`--batch-size=N` 透传，Commandlet 每 N 个资产显式 `CollectGarbage`。
- **文档**：README、USER_MANUAL、DEPLOYMENT、IMPORT_SPEC、INJECT_RELEASE、TROUBLESHOOTING。

### 已知限制

- 目标 CARLA 版本锁定 0.9.16（UE 4.26），不承诺兼容其他版本；
- 六轮及以上多轴车型暂不支持（Schema 红线 `wheels ∈ {2, 4}`）；
- C++ 插件需在使用方 UE 4.26 + CARLA 源码环境编译（本仓库交付源码与编译验证清单，见 DEPLOYMENT.md）；
- 通道 B（`--skip-factory`）注册的车辆不支持 Blueprint Library `filter` 检索；
- pak 格式打包依赖 UnrealPak，无引擎环境时返回退出码 3。
