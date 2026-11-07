// Copyright CarlaAutoPipe Team. All Rights Reserved.
//
// 移植说明：基于 UE 4.26 IAssetTools / FAssetRegistry / UObject 反射公开 API 编写，
// 部署时对照目标引擎头文件核对签名（docs/DEPLOYMENT.md 验证清单）。
#include "GoldenTemplateCopier.h"

#include "CarlaAssetImporter.h"
#include "VehicleBlueprintAssembler.h"
#include "AssetRegistryModule.h"
#include "AssetToolsModule.h"
#include "IAssetTools.h"
#include "ObjectTools.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "FileHelpers.h"
#include "Engine/SkeletalMesh.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "Engine/Blueprint.h"
#include "UObject/Package.h"
#include "UObject/UObjectIterator.h"

TArray<TWeakObjectPtr<UObject>>& UCarlaGoldenTemplateCopier::GetTrackedAssets()
{
	static TArray<TWeakObjectPtr<UObject>> Tracked;
	return Tracked;
}

void UCarlaGoldenTemplateCopier::TrackDirtyAsset(UObject* Asset)
{
	if (Asset)
	{
		Asset->MarkPackageDirty();
		GetTrackedAssets().Add(Asset);
	}
}

bool UCarlaGoldenTemplateCopier::DuplicateTemplate(const FString& TargetDir,
	TMap<FName, UObject*>& OutSrcToDst)
{
	// 1. 枚举模板目录全部资产
	FAssetRegistryModule& AssetRegistryModule =
		FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry");
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

	FARFilter Filter;
	Filter.PackagePaths.Add(*GetTemplateRootPath());
	Filter.bRecursivePaths = true;
	TArray<FAssetData> TemplateAssets;
	AssetRegistry.GetAssets(Filter, TemplateAssets);
	if (TemplateAssets.Num() == 0)
	{
		UE_LOG(LogCarlaAssetImport, Error,
			TEXT("Golden template directory empty: %s"), *GetTemplateRootPath());
		return false;
	}

	// 2. IAssetTools 批量复制（DuplicateAsset 逐个复制并保留类结构）
	IAssetTools& AssetTools = FModuleManager::LoadModuleChecked<FAssetToolsModule>("AssetTools").Get();
	for (const FAssetData& Data : TemplateAssets)
	{
		UObject* Src = Data.GetAsset();
		if (!Src)
		{
			continue;
		}
		const FString SrcName = Data.GetName().ToString();
		UObject* Dst = AssetTools.DuplicateAsset(SrcName, TargetDir, Src);
		if (!Dst)
		{
			UE_LOG(LogCarlaAssetImport, Error, TEXT("Duplicate failed for %s"), *SrcName);
			return false;
		}
		OutSrcToDst.Add(Data.GetName(), Dst);
		TrackDirtyAsset(Dst);
	}
	return OutSrcToDst.Num() > 0;
}

int32 UCarlaGoldenTemplateCopier::ReplaceReferences(UObject* Asset,
	const TMap<FSoftObjectPath, FSoftObjectPath>& ReplaceMap)
{
	// 引用改写器：遍历对象全部 ObjectProperty（含软引用），命中映射即替换。
	int32 Replaced = 0;
	for (TFieldIterator<FProperty> It(Asset->GetClass()); It; ++It)
	{
		FObjectProperty* ObjProp = CastField<FObjectProperty>(*It);
		FSoftObjectProperty* SoftProp = CastField<FSoftObjectProperty>(*It);
		if (ObjProp && ObjProp->PropertyClass)
		{
			UObject* Value = ObjProp->GetObjectPropertyValue(
				ObjProp->ContainerPtrToValuePtr<void>(Asset));
			if (Value)
			{
				const FSoftObjectPath Path(Value);
				if (const FSoftObjectPath* New = ReplaceMap.Find(Path))
				{
					UObject* Resolved = New->TryResolveObject();
					if (Resolved)
					{
						ObjProp->SetObjectPropertyValue(
							ObjProp->ContainerPtrToValuePtr<void>(Asset), Resolved);
						++Replaced;
					}
				}
			}
		}
		else if (SoftProp)
		{
			const FSoftObjectPath Value = SoftProp->GetSoftObjectPath(
				SoftProp->ContainerPtrToValuePtr<void>(Asset));
			if (const FSoftObjectPath* New = ReplaceMap.Find(Value))
			{
				SoftProp->Set(
					SoftProp->ContainerPtrToValuePtr<void>(Asset), New->Clone());
				++Replaced;
			}
		}
	}
	return Replaced;
}

UBlueprint* UCarlaGoldenTemplateCopier::DuplicateAndAssemble(
	const FCarlaVehicleManifest& Manifest, USkeletalMesh* NewMesh,
	UPhysicsAsset* NewPhysics, const FGuid& BatchId)
{
	const FString ModelName = Manifest.Model.Left(1).ToUpper() + Manifest.Model.RightChop(1);
	const FString TargetDir = FString::Printf(TEXT("/Game/Carla/Blueprints/Vehicles/%s"), *ModelName);

	TMap<FName, UObject*> Copied;
	if (!DuplicateTemplate(TargetDir, Copied))
	{
		return nullptr;
	}

	// 组装引用替换映射：模板内旧 mesh/physics -> 新导入资产
	TMap<FSoftObjectPath, FSoftObjectPath> ReplaceMap;
	const FString OldMeshPath = TEXT(
		"/Game/Carla/Static/Vehicle/_Template/Template_SkelMesh.Template_SkelMesh");
	const FString OldPhysPath = TEXT(
		"/Game/Carla/Static/Vehicle/_Template/Template_Physics.Template_Physics");
	ReplaceMap.Add(FSoftObjectPath(OldMeshPath), FSoftObjectPath(NewMesh));
	ReplaceMap.Add(FSoftObjectPath(OldPhysPath), FSoftObjectPath(NewPhysics));

	UBlueprint* VehicleBP = nullptr;
	for (TPair<FName, UObject*>& Pair : Copied)
	{
		UObject* Asset = Pair.Value;
		ReplaceReferences(Asset, ReplaceMap);

		if (UBlueprint* BP = Cast<UBlueprint>(Asset))
		{
			// 红线：车辆 Pawn 父类必须保持 BaseVehiclePawn（模板已满足，此处断言）
			if (BP->ParentClass &&
				BP->ParentClass->GetName().Contains(TEXT("BaseVehiclePawn")) == false &&
				BP->GetName().StartsWith(TEXT("BP_")))
			{
				UE_LOG(LogCarlaAssetImport, Error,
					TEXT("REDLINE: %s parent class is %s (expect BaseVehiclePawn)"),
					*BP->GetName(), *BP->ParentClass->GetName());
				return nullptr;
			}
			// 蓝图属性改写：Mesh / PhysicsAsset / 车轮半径等通过 CDO 设置
			UCarlaVehicleBlueprintAssembler::ApplyManifest(BP, Manifest, NewMesh, NewPhysics, Pair.Key);
			if (Pair.Key.ToString().StartsWith(TEXT("BP_")))
			{
				VehicleBP = BP;   // 主车辆蓝图
			}
		}
		TrackDirtyAsset(Asset);
	}

	if (!VehicleBP)
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("VehicleBP not found in template batch %s"),
			*BatchId.ToString());
	}
	return VehicleBP;
}

bool UCarlaGoldenTemplateCopier::SaveGeneratedAssets()
{
	TArray<UPackage*> PackagesToSave;
	for (TWeakObjectPtr<UObject>& Weak : GetTrackedAssets())
	{
		if (UObject* Asset = Weak.Get())
		{
			UPackage* Pkg = Asset->GetPackage();
			// 蓝图需先编译再保存，确保引用改写落进序列化数据
			if (UBlueprint* BP = Cast<UBlueprint>(Asset))
			{
				FKismetEditorUtilities::CompileBlueprint(BP);
			}
			if (Pkg && !PackagesToSave.Contains(Pkg))
			{
				PackagesToSave.Add(Pkg);
			}
		}
	}
	GetTrackedAssets().Reset();
	if (PackagesToSave.Num() == 0)
	{
		return true;
	}
	const bool bSaved = FEditorFileUtils::SaveDirtyPackages(
		true,   // bPromptUserToSave=false 语义（Commandlet 无交互）
		true,   // bSaveMapPackages
		false,  // bSaveContentBrowserPackages
		true,   // bFastSave（跳过无关脏包）
		false);
	UE_LOG(LogCarlaAssetImport, Log, TEXT("SaveGeneratedAssets: %d packages, saved=%d"),
		PackagesToSave.Num(), bSaved ? 1 : 0);
	return bSaved;
}
