// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "AssetManifest.h"

class USkeletalMesh;
class UPhysicsAsset;

/**
 * 车辆物理资产自动化构建（V1.2 §4.4）。
 *
 * 流程：清理默认胶囊 → 车身 SingleConvexHull → 车轮 Sphere/Kinematic/HitEvents
 *      → 骨骼约束 → 断言校验（骨骼与碰撞体一一对应，防转向失效）。
 */
class UCarlaVehiclePhysicsBuilder
{
public:
	/** 依据 Manifest 构建物理资产；失败返回 nullptr。 */
	static UPhysicsAsset* Build(USkeletalMesh* Mesh, const FCarlaVehicleManifest& Manifest);

	/** 断言校验：每根车轮骨骼必须有对应几何体，返回缺失骨骼名列表。 */
	static TArray<FString> ValidateBoneCoverage(const UPhysicsAsset* Phys,
		const FCarlaVehicleManifest& Manifest);
};
