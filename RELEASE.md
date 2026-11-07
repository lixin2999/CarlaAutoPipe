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

## V1.0.1 — 2026-11-07（代码审查整改）

依据《详细设计文档 V1.4》对全部代码完成专项审查（功能符合性 / 内存与边界异常 /
并发与性能），本节为整改清单。全部整改附带新增回归用例，pytest 77 项全部通过。

### 修复

- **inject 幂等与回滚全通路闭环**（设计目标 5/§4.5）：
  - pak 通路指纹由 `(文件名, "pak")` 占位修正为 **文件内容 SHA-256**，并前置幂等检查
    （重复注入相同 pak 直接跳过，`--force` 可强制重注；包内容变更能被感知）；
    记录与比对严格同源同算法，消除既往“指纹记录与比对不一致”同类缺陷；
  - Linux ImportAssets.sh 通路补齐 **注入前快照备份 + 失败真回滚 + 成功后指纹记录**
    （此前传 `None` 仅输出“无需回滚”误导信息，且从不记录指纹）；
  - 逐文件指纹改为 **流式哈希**（复用 `checksum.file_sha256`，pack 侧同步），
    消除大体积 .uasset 整文件读入内存的 OOM 风险。
- **zip 解包路径穿越防护**：`read_package` 对 zip 条目增加与 tar.gz 同款的绝对路径/`..`
    预检，恶意或损坏包不再能写出目标目录之外（报 `PKG_CORRUPT`，退出码 1）。
- **smoke JUnit XML 真实落地**：`write_junit` 此前无任何调用点（V1.0.0 文档声称失实），
    现每次冒烟自动产出 `reports/smoke.junit.xml` 并计入 artifacts；属性值全部 XML
    转义，含引号/尖括号的诊断详情不再破坏 XML 合法性。
- **smoke 参数透传**：地图冒烟 TrafficManager 探测改用 CLI 传入的 `--host/--port`，
    非默认端口下 check03 不再必失败；探测 Client 补齐 10s 超时。
- **validate 退出码一致性**：Blender 侧报告解析失败但退出码为 1 时，兜底补录 ERROR
    并附 stderr 尾部，保证“存在 ERROR → 退出码 1”契约不留缺口。
- **配置损坏可读化**：`settings.json` JSON 语法错误新增 `SettingsError`，CLI 映射为
    退出码 3（`ENV_SETTINGS_INVALID`）并附修复指引，不再落入意外异常兜底报 2。
- **Ctrl+C 语义修正**：KeyboardInterrupt 退出码由 2（引擎内部错误）改为 130（128+SIGINT 惯例）。
- **Blender 校验边界**（validate_mesh.py）：空包围盒集、`wheels∉{2,4}`（单独调用时）
    直接 ERROR 阻断，修复两轮车骨骼子集切片表达式 `[:declared-2+2]` 恒为全集的写法；
    删除退化面检测中的死代码分支。
- **冒烟资源回收**：车辆 check07 的 Lidar 传感器与 QueueSensor 登记统一由 `cleanup()`
    销毁（异常路径不泄漏）；地图 check03 测试车辆 try/finally 销毁；check04 不再误销毁
    环境已有行人，只销毁本次生成个体。

### 完善

- **GUI 注入二次确认改为真实差异清单**：新增 `gui/preview.py`（只读复用 CLI 核心函数
    解包比对，不写目标、不破薄壳契约），预览不可用时明示原因，不再展示占位假数据。
- **ImportAssets.sh 异常精细处理**：bash 缺失/启动失败 → 退出码 3（`ENV_BASH_MISSING`，
    提示 Windows 运行机改用 zip 通路）；超时 → 退出码 2（`IMPORT_SH_TIMEOUT`）并回滚。
- **窗口标题与版本号单一来源**：GUI 标题改读包版本（`gui.__version__`）。

### 修复（UE 4.26 C++ 插件，需重新编译，见 DEPLOYMENT）

- `TemplateHashGuard`：模板目录相对路径排序改为大小写敏感码点序（`FString::Sort` 默认
  IgnoreCase），与 Python `checksum.py` 严格对齐，消除混合大小写文件名下哈希卡点误报
  退出码 3 的风险；
- `CarlaAssetImportCommandlet`：引擎侧 JSON 报告 `exit_code` 写入真实返回码 0/1/2/3
  （此前恒为 HasErrors 推断的 0/1，GUI/CI 会把环境错误误读为校验失败）；
- `MapImporter::WaitForSceneReady`：等待循环内显式 `ProcessAsyncLoading(true)` 泵送异步
  加载管线（此前纯 Sleep 轮询无法推进加载，可能恒定超时退出码 2）；物理就绪检查由全局
  `TObjectIterator` 收窄为 `FActorIterator` 限目标世界，消除大场景轮询性能开销；
- `VehiclePhysicsBuilder`：骨骼索引 `INDEX_NONE`（车身/车轮骨骼未命中）时报错失败而非
  静默生成未绑定碰撞体；失败路径 `MarkAsGarbage()` 释放 `RF_Standalone` 临时资产，
  避免进程内常驻。

### 已知限制（本次审查发现，需 UE 实机验证后排期，未在本版修改）

- 地图管线缺关卡加载/保存环节：`MapImporter` 全程使用当前编辑器默认世界，地形
  StaticMesh 所在包未显式保存（`LoadedWorld` 成员声明后未使用）；
- `FbxImporter::ImportStaticMesh` 忽略 `bSimpleCollision` 参数，简模轨“自动简单碰撞/降精度”
  未实际落地；
- `GoldenTemplateCopier::SaveGeneratedAssets` 依赖全局 SaveDirtyPackages 而非显式保存
  收集到的包列表，弱指针追踪与注释不符（插入 GC 时可能静默漏存）；
- `FlushPendingRegistrations` 假设批内同一 VehicleFactory，多工厂混合批次仅编译首个；
  `-batch-size` 分片 GC 在“单进程单资产”架构下仅对 BatchSize=1 生效；
- C 轨“人工审核卡点”仅为流程约定（文档/报错指引），工具侧无强制拦截。

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
