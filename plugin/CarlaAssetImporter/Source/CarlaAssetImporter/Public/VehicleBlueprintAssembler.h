// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "AssetManifest.h"

class USkeletalMesh;
class UPhysicsAsset;
class UBlueprint;

/**
 * 车辆蓝图装配器（V1.2 §4.3 改写映射表执行者）。
 *
 * 对模板复制出的每个蓝图按资产角色改写 CDO 属性：
 *   AnimBP            -> Skeleton / Mesh 引用（保留程序化动画逻辑）
 *   <Model>_FrontWheel / RearWheel -> 半径、宽度、转向角、手刹、轮胎配置
 *   BP_<Model>        -> Mesh / PhysicsAsset 引用 + 质量 / 质心
 * 红线：不改节点图、不改父类逻辑，仅动引用型与数值型属性。
 */
class UCarlaVehicleBlueprintAssembler
{
public:
	/** 按资产名角色应用 Manifest 改写。返回是否识别并处理。 */
	static bool ApplyManifest(UBlueprint* BP, const FCarlaVehicleManifest& Manifest,
		USkeletalMesh* NewMesh, UPhysicsAsset* NewPhysics, const FName& AssetName);

	/** 设置对象树上一级属性（跨模块反射写入，规避对 Carla 模块的编译期依赖）。 */
	static bool SetSoftClassPathProperty(UObject* Object, const TCHAR* PropName,
		const FSoftObjectPath& Value);
	static bool SetNumericProperty(UObject* Object, const TCHAR* PropName, float Value);
	static bool SetBoolProperty(UObject* Object, const TCHAR* PropName, bool Value);
};
