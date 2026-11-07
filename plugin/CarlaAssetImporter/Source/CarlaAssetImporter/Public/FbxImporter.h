// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "AssetManifest.h"

class USkeletalMesh;

/**
 * 固化参数 FBX 导入器（L2 引擎导入层，V1.2 §3.2）。
 * 导入参数全部常量化，消除「导入参数不统一」根因。
 */
class UCarlaFbxImporter
{
public:
	/** 导入骨骼网格体并挂接官方标准 Skeleton（红线：不创建新骨架）。 */
	static USkeletalMesh* ImportSkeletalMesh(const FCarlaVehicleManifest& Manifest);

	/** 导入静态网格体（地图地形），自动生成简单碰撞。 */
	static UStaticMesh* ImportStaticMesh(const FString& FbxPath,
		const FString& PackagePath, const FString& AssetName, bool bSimpleCollision);

	/** 目标标准骨架路径（VehicleSkeleton 官方资产）。 */
	static FString GetStandardSkeletonPath()
	{
		return TEXT("/Game/Carla/Static/Vehicle/VehicleSkeleton.VehicleSkeleton");
	}

	/** 生成资产包路径：/Game/Carla/Blueprints/Vehicles/<Model>/SK_<Model>。 */
	static void BuildAssetLocation(const FString& ModelLower, const FString& Suffix,
		FString& OutPackagePath, FString& OutAssetName);
};
