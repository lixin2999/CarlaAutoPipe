// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"

/** Manifest 解析结果的内存模型（对应 schemas/vehicle.schema.json 与 map.schema.json）。 */

USTRUCT()
struct FCarlaVehicleMeshConfig
{
	GENERATED_BODY()

	FString Unit = TEXT("cm");
	FString ForwardAxis = TEXT("+X");
	FString UpAxis = TEXT("+Z");
	FString FbxPath;
};

USTRUCT()
struct FCarlaPhysicsConfig
{
	GENERATED_BODY()

	FString BodyType = TEXT("SingleConvexHull");
	FString WheelPrimitive = TEXT("Sphere");
	FString WheelPhysicsType = TEXT("Kinematic");
	bool bGenerateHitEvents = true;
	float ShapeRadiusM = 0.35f;   // 车轮球形碰撞体半径（米，构建时转厘米）
	float MassKg = 1845.f;
	FVector CenterOfMass = FVector::ZeroVector;
};

USTRUCT()
struct FCarlaRegistration
{
	GENERATED_BODY()

	FString VehicleFactoryPath =
		TEXT("/Game/Carla/Blueprints/Vehicles/VehicleFactory.VehicleFactory");
	FString BlueprintParent = TEXT("BaseVehiclePawn");   // 绝对红线
	bool bSkipFactory = false;                           // true → 降级通道 B
};

/** 车辆 Manifest（V1.4 §4.1）。 */
USTRUCT()
struct FCarlaVehicleManifest
{
	GENERATED_BODY()

	FString TargetCarla = TEXT("0.9.16");
	FString Make;               // 已强制小写
	FString Model;              // 已强制小写
	FString Class;
	int32 Generation = 1;
	int32 Wheels = 4;
	FString BaseType;
	FCarlaVehicleMeshConfig Mesh;
	FCarlaPhysicsConfig Physics;
	TArray<FLinearColor> Colors;
	FCarlaRegistration Registration;
	FString GoldenTemplateChecksum;   // SHA-256，64 位小写十六进制
	FString SourceManifestPath;       // 原始 JSON 文件（归档用）

	FString GetAssetId() const { return FString::Printf(TEXT("vehicle.%s.%s"), *Make, *Model); }
};

/** 地图 Manifest（核心字段：map_name / xodr_path / terrain_fbx_path / navmesh_settings）。 */
USTRUCT()
struct FCarlaMapManifest
{
	GENERATED_BODY()

	FString TargetCarla = TEXT("0.9.16");
	FString MapName;              // TownXX
	FString Track = TEXT("standard");
	FString XodrPath;
	FString TerrainFbxPath;
	FString TextureDir;
	bool bEnableVehicleNav = true;
	bool bEnablePedestrianNav = true;
	float AgentRadiusCM = 30.f;
	float AgentHeightCM = 180.f;
	float MaxClimbCM = 30.f;
	bool bMaterialAdapt = true;   // 自定义材质轨关闭
	bool bSimpleCollision = false;
	bool bSkipNavMesh = false;    // --skip-navmesh
	FString SourceManifestPath;
};

/** Manifest 加载与 Schema 关键字段校验（引擎内二次卡点）。 */
class FCarlaAssetManifestLoader
{
public:
	/** 加载并校验车辆 Manifest。失败时 OutError 携带可诊断信息，返回 false（退出码 1）。 */
	static bool LoadVehicle(const FString& Path, FCarlaVehicleManifest& Out, FString& OutError);

	/** 加载并校验地图 Manifest。 */
	static bool LoadMap(const FString& Path, FCarlaMapManifest& Out, FString& OutError);
};
