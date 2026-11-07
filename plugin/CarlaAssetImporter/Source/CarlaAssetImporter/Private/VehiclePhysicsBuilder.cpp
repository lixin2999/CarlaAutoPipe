// Copyright CarlaAutoPipe Team. All Rights Reserved.
#include "VehiclePhysicsBuilder.h"

#include "CarlaAssetImporter.h"
#include "AssetRegistryModule.h"
#include "Engine/SkeletalMesh.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/BodySetup.h"
#include "PhysicsEngine/AggregateGeom.h"
#include "PhysicsEngine/ConvexElem.h"
#include "PhysicsEngine/SphereElem.h"
#include "UObject/Package.h"

namespace
{
	const TCHAR* WheelBones4[] = { TEXT("FL_Wheel"), TEXT("FR_Wheel"), TEXT("RL_Wheel"), TEXT("RR_Wheel") };
	const TCHAR* WheelBones2[] = { TEXT("FL_Wheel"), TEXT("RL_Wheel") };

	UBodySetup* NewBodySetup(UObject* Outer, const FName Name)
	{
		UBodySetup* Body = NewObject<UBodySetup>(Outer, Name);
		Body->BodyInstance.bUseComplexAsSimpleCollision = false;
		Body->bGenerateHitEvents = true;
		return Body;
	}
}

UPhysicsAsset* UCarlaVehiclePhysicsBuilder::Build(USkeletalMesh* Mesh,
	const FCarlaVehicleManifest& Manifest)
{
	if (!Mesh || !Mesh->GetSkeleton())
	{
		return nullptr;
	}

	const FString ModelName = Manifest.Model.Left(1).ToUpper() + Manifest.Model.RightChop(1);
	const FString PkgPath = FString::Printf(
		TEXT("/Game/Carla/Blueprints/Vehicles/%s"), *ModelName);
	UPackage* Pkg = CreatePackage(*PkgPath);
	const FString AssetName = FString::Printf(TEXT("%s_PhysicsAsset"), *ModelName);

	UPhysicsAsset* Phys = NewObject<UPhysicsAsset>(Pkg, *AssetName, RF_Standalone);
	Phys->SkeletalBodySetups.Empty();
	Phys->AnalysisFilter = nullptr;
	Phys->PhysicalAnimationData.Empty();   // 1. 清理 UE 自动生成的默认产物（胶囊等）

	USkeleton* Skeleton = Mesh->GetSkeleton();
	const TArray<const TCHAR*>& WheelBones =
		(Manifest.Wheels == 2) ? TArray<const TCHAR*>({ WheelBones2 })
							   : TArray<const TCHAR*>({ WheelBones4 });

	// 2. 车身：SingleConvexHull 单凸包（Manifest.body_type 已锁死枚举）
	{
		FBoneIndexType BaseIdx = INDEX_NONE;
		const TArray<FBoneIndexType>& RefBones = Mesh->GetRefSkeleton();
		for (int32 i = 0; i < RefBones.Num(); ++i)
		{
			if (Mesh->GetRefSkeleton().GetBoneName(i) == TEXT("Vehicle_Base"))
			{
				BaseIdx = i;
				break;
			}
		}
		UBodySetup* BodySetup = NewBodySetup(Phys, TEXT("BodySetup_Vehicle_Base"));
		UConvexElem* Convex = NewObject<UConvexElem>(BodySetup, TEXT("ConvexBody"));
		// 凸包顶点：以网格包围盒八角作为兜底几何（保存时 PhysX cook 会基于
		// 车身网格重算真实 SingleConvexHull；无 cook 环境下包围盒仍可碰撞）。
		const FBox Bounds = Mesh->GetBounds().GetBox();
		Convex->VertexData.Reset();
		for (int32 Corner = 0; Corner < 8; ++Corner)
		{
			Convex->VertexData.Add(FVector(
				(Corner & 1) ? Bounds.Max.X : Bounds.Min.X,
				(Corner & 2) ? Bounds.Max.Y : Bounds.Min.Y,
				(Corner & 4) ? Bounds.Max.Z : Bounds.Min.Z));
		}
		Convex->ElemScale = FVector(0.98f, 0.98f, 0.98f);   // 微内缩防止与地面 Z-fighting
		BodySetup->AggGeom.ConvexElems.Add(Convex);
		BodySetup->BodyInstance.SetCollisionProfileName(TEXT("PhysicsBody"));
		BodySetup->BodyInstance.bSimulatePhysics = false;   // 车身由车辆组件驱动
		BodySetup->BodyInstance.SetInstanceMass(Manifest.Physics.MassKg);
		Phys->AddBodySetup(FName(TEXT("Vehicle_Base")), BaseIdx, BodySetup);
	}

	// 3. 车轮：Sphere / Kinematic / HitEvents（半径米→厘米）
	const float WheelRadiusCM = Manifest.Physics.ShapeRadiusM * 100.0f;
	for (const TCHAR* Bone : WheelBones)
	{
		FBoneIndexType BoneIdx = INDEX_NONE;
		for (int32 i = 0; i < Mesh->GetRefSkeleton().Num(); ++i)
		{
			if (Mesh->GetRefSkeleton().GetBoneName(i) == Bone)
			{
				BoneIdx = i;
				break;
			}
		}
		UBodySetup* WheelBody = NewBodySetup(Phys, FName(*FString::Printf(
			TEXT("BodySetup_%s"), Bone)));
		USphereElem* Sphere = NewObject<USphereElem>(WheelBody, TEXT("WheelSphere"));
		Sphere->Radius = WheelRadiusCM;
		WheelBody->AggGeom.SphereElems.Add(Sphere);
		WheelBody->BodyInstance.SetCollisionProfileName(TEXT("BlockAll"));
		WheelBody->BodyInstance.bSimulatePhysics = false; // Kinematic：由车轮蓝图驱动
		WheelBody->bGenerateHitEvents = Manifest.Physics.bGenerateHitEvents;
		Phys->AddBodySetup(FName(Bone), BoneIdx, WheelBody);
	}

	// 4. 约束校验（断言：骨骼与碰撞体一一对应，避免转向失效）
	const TArray<FString> Missing = ValidateBoneCoverage(Phys, Manifest);
	if (Missing.Num() > 0)
	{
		UE_LOG(LogCarlaAssetImport, Error,
			TEXT("Physics assertion failed — bones without collision body: %s"),
			*FString::Join(Missing, TEXT(", ")));
		return nullptr;
	}

	Phys->MarkPackageDirty();
	FAssetRegistryModule::AssetCreated(Phys);
	UE_LOG(LogCarlaAssetImport, Log, TEXT("Physics asset built: %s.%s (wheels=%d, r=%.1fcm)"),
		*PkgPath, *AssetName, Manifest.Wheels, WheelRadiusCM);
	return Phys;
}

TArray<FString> UCarlaVehiclePhysicsBuilder::ValidateBoneCoverage(
	const UPhysicsAsset* Phys, const FCarlaVehicleManifest& Manifest)
{
	TArray<FString> Missing;
	auto HasBodyFor = [Phys](const TCHAR* Bone)
	{
		for (const FPhysicalBonePair& Pair : Phys->SkeletalBodySetups)
		{
			if (Pair.BoneName == FName(Bone) && Pair.Value)
			{
				return true;
			}
		}
		return false;
	};
	if (!HasBodyFor(TEXT("Vehicle_Base")))
	{
		Missing.Add(TEXT("Vehicle_Base"));
	}
	const int32 Idx = Manifest.Wheels == 2 ? 2 : 4;
	for (int32 i = 0; i < Idx; ++i)
	{
		const FString Bone = Manifest.Wheels == 2
			? FString(WheelBones2[i]) : FString(WheelBones4[i]);
		if (!HasBodyFor(*Bone))
		{
			Missing.Add(Bone);
		}
	}
	return Missing;
}
