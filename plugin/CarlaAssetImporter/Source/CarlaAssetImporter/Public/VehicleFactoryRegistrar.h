// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "AssetManifest.h"

class UBlueprint;

/**
 * ★VehicleFactory 延迟编译与事务队列注册（V1.4 §4.4 / V1.2 §4.5）。
 *
 * 通道 A（官方标准注册）：
 *   定位 VehicleFactory 蓝图 CDO → 幂等检查 → 向 Vehicles 数组注入
 *   FVehicleParameters（Class 采用 TSoftClassPtr 软引用写入）→ 入队。
 *   单次追加不触发编译；Commandlet 批处理末尾统一调用 FlushPendingRegistrations()
 *   执行一次 CompileBlueprint + MarkPackageDirty + 保存，消除重复全图编译开销。
 *
 * 通道 B（降级加载）：Manifest registration.skip_factory=true 时跳过注册，
 *   运行端按资产路径直接加载（不支持 filter 检索与 ScenarioRunner model=）。
 */
class UCarlaVehicleFactoryRegistrar
{
public:
	/** 注入一条车辆注册数据并入事务队列（不编译）。成功入队返回 true。 */
	static bool EnqueueRegistration(const FCarlaVehicleManifest& Manifest,
		UBlueprint* VehicleBP, bool bDryRun);

	/** ★批处理末尾统一编译并保存 VehicleFactory（事务队列 Flush）。返回失败条数。 */
	static int32 FlushPendingRegistrations(bool bDryRun);

	/** 队列中待编译条目数（测试与诊断用）。 */
	static int32 GetPendingCount();

	/** 清空队列（异常路径回滚用）。 */
	static void ResetQueue();

private:
	struct FPendingRegistration
	{
		FCarlaVehicleManifest Manifest;
		FString VehicleClassPath;   // BP_<Model>_C 软引用路径
		bool bNewEntry = false;     // 幂等检查后确属新增才编译
	};
	static TArray<FPendingRegistration>& GetQueue();
};
