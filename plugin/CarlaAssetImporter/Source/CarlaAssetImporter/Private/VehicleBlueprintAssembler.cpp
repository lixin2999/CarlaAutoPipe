// Copyright CarlaAutoPipe Team. All Rights Reserved.
#include "VehicleBlueprintAssembler.h"

#include "CarlaAssetImporter.h"
#include "Engine/Blueprint.h"
#include "Engine/SkeletalMesh.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "UObject/UnrealType.h"

bool UCarlaVehicleBlueprintAssembler::SetSoftClassPathProperty(UObject* Object,
	const TCHAR* PropName, const FSoftObjectPath& Value)
{
	FProperty* Prop = Object->GetClass()->FindPropertyByName(PropName);
	if (FSoftObjectProperty* Soft = CastField<FSoftObjectProperty>(Prop))
	{
		Soft->Set(Soft->ContainerPtrToValuePtr<void>(Object), Value.Clone());
		return true;
	}
	if (FClassProperty* ClassProp = CastField<FClassProperty>(Prop))
	{
		UClass* Resolved = Value.TryResolveClass();
		if (Resolved)
		{
			ClassProp->SetObjectPropertyValue(
				ClassProp->ContainerPtrToValuePtr<void>(Object), Resolved);
			return true;
		}
	}
	return false;
}

bool UCarlaVehicleBlueprintAssembler::SetNumericProperty(UObject* Object,
	const TCHAR* PropName, float Value)
{
	FProperty* Prop = Object->GetClass()->FindPropertyByName(PropName);
	if (FFloatProperty* F = CastField<FFloatProperty>(Prop))
	{
		F->Set(F->ContainerPtrToValuePtr<void>(Object), Value);
		return true;
	}
	if (FDoubleProperty* D = CastField<FDoubleProperty>(Prop))
	{
		D->Set(D->ContainerPtrToValuePtr<void>(Object), Value);
		return true;
	}
	return false;
}

bool UCarlaVehicleBlueprintAssembler::SetBoolProperty(UObject* Object,
	const TCHAR* PropName, bool Value)
{
	FProperty* Prop = Object->GetClass()->FindPropertyByName(PropName);
	if (FBoolProperty* B = CastField<FBoolProperty>(Prop))
	{
		B->Set(B->ContainerPtrToValuePtr<void>(Object), Value);
		return true;
	}
	return false;
}

bool UCarlaVehicleBlueprintAssembler::ApplyManifest(UBlueprint* BP,
	const FCarlaVehicleManifest& Manifest, USkeletalMesh* NewMesh,
	UPhysicsAsset* NewPhysics, const FName& AssetName)
{
	if (!BP || !BP->GeneratedClass)
	{
		return false;
	}
	UObject* CDO = BP->GeneratedClass->GetDefaultObject();
	if (!CDO)
	{
		return false;
	}
	const FString Name = AssetName.ToString();
	bool bHandled = false;

	if (Name.Contains(TEXT("AnimBP")))
	{
		// 动画蓝图：仅刷新 Skeleton 引用（程序化动画逻辑保持原样）
		SetSoftClassPathProperty(CDO, TEXT("SkeletonToUse"), FSoftObjectPath(NewMesh->GetSkeleton()));
		bHandled = true;
	}
	else if (Name.Contains(TEXT("FrontWheel")) || Name.Contains(TEXT("RearWheel")))
	{
		// 车轮蓝图：半径（米，WheeledVehicleWheel 约定）与轮胎配置
		const bool bFront = Name.Contains(TEXT("FrontWheel"));
		SetNumericProperty(CDO, TEXT("Radius"), Manifest.Physics.ShapeRadiusM);
		SetNumericProperty(CDO, TEXT("Width"), Manifest.Physics.ShapeRadiusM * 0.6f);
		if (bFront)
		{
			SetNumericProperty(CDO, TEXT("MaxSteerAngle"), 70.0f); // 前轮转向
		}
		SetBoolProperty(CDO, TEXT("bHandbrake"), !bFront);          // 后轮手刹（CARLA 惯例）
		bHandled = true;
	}
	else if (Name.StartsWith(TEXT("BP_")))
	{
		// 车辆主蓝图：网格 / 物理资产 / 质量 / 质心
		SetSoftClassPathProperty(CDO, TEXT("Mesh"), FSoftObjectPath(NewMesh));
		SetSoftClassPathProperty(CDO, TEXT("PhysicsAsset"), FSoftObjectPath(NewPhysics));
		SetNumericProperty(CDO, TEXT("Mass"), Manifest.Physics.MassKg);
		if (FProperty* ComProp = CDO->GetClass()->FindPropertyByName(TEXT("CenterOfMass")))
		{
			if (FStructProperty* Struct = CastField<FStructProperty>(ComProp);
				Struct && Struct->Struct == TBaseStructure<FVector>::Get())
			{
				FVector* Com = Struct->ContainerPtrToValuePtr<FVector>(CDO);
				*Com = Manifest.Physics.CenterOfMass;   // 已转厘米
			}
		}
		bHandled = true;
	}

	if (bHandled)
	{
		BP->MarkPackageDirty();
		UE_LOG(LogCarlaAssetImport, Log, TEXT("Blueprint rewritten: %s"), *Name);
	}
	else
	{
		UE_LOG(LogCarlaAssetImport, Warning,
			TEXT("Unrecognized template asset '%s' — kept as duplicate"), *Name);
	}
	return bHandled;
}
