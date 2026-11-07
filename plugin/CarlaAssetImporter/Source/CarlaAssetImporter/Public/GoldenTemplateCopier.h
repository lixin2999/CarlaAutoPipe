// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "AssetManifest.h"

class USkeletalMesh;
class UPhysicsAsset;
class UBlueprint;

/**
 * ★黄金模板复制 + 引用改写（V1.4 §4.3 / V1.2 §4.3）。
 *
 * 核心策略：禁止从零生成蓝图节点图。基于官方验证过的原生资产（默认拆解自
 * vehicle.tesla.model3）通过 IAssetTools 复制完整资产目录，仅改写引用型属性，
 * 保证产出蓝图与官方原生资产字节级结构一致。
 *
 * 模板目录（构建时只读）：/Game/Carla/Blueprints/Vehicles/_Template/
 */
class UCarlaGoldenTemplateCopier
{
public:
	/** 模板目录内容路径。 */
	static FString GetTemplateRootPath()
	{
		return TEXT("/Game/Carla/Blueprints/Vehicles/_Template");
	}

	/**
	 * 复制模板目录到目标车型目录并批量改写引用，产出 VehicleBP。
	 * 改写映射（V1.2 §4.3 表）：
	 *   SkeletalMesh  -> 新导入网格（关联标准 Skeleton）
	 *   AnimBP        -> Skeleton / Mesh 引用
	 *   Front/RearWheelBP -> 半径、宽度、转向角、手刹、轮胎参数
	 *   VehicleBP     -> Mesh/AnimBP/车轮引用 + 质量/质心
	 * @param BatchId 同批资产用于事务队列归组
	 */
	static UBlueprint* DuplicateAndAssemble(const FCarlaVehicleManifest& Manifest,
		USkeletalMesh* NewMesh, UPhysicsAsset* NewPhysics, const FGuid& BatchId);

	/** 保存本批生成的全部资产（按依赖顺序，VehicleFactory 由注册器最后保存）。 */
	static bool SaveGeneratedAssets();

	/** 登记需要落盘的资产（供 SaveGeneratedAssets 统一保存）。 */
	static void TrackDirtyAsset(UObject* Asset);

private:
	/** 复制模板目录全部资产到目标路径，返回 源资产->新资产 映射。 */
	static bool DuplicateTemplate(const FString& TargetDir,
		TMap<FName, UObject*>& OutSrcToDst);

	/** 递归替换对象内的软/硬对象引用（引用改写器）。 */
	static int32 ReplaceReferences(UObject* Asset,
		const TMap<FSoftObjectPath, FSoftObjectPath>& ReplaceMap);

	/** 本批已生成待保存资产表（Rooted 直到保存完成）。 */
	static TArray<TWeakObjectPtr<UObject>>& GetTrackedAssets();
};
