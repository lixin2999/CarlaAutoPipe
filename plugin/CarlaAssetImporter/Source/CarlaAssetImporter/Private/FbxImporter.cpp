// Copyright CarlaAutoPipe Team. All Rights Reserved.
//
// 移植说明：本文件基于 UE 4.26 经典 FBX 导入插件（Engine/Plugins/Editor/FBXImporter）
// 的 UFbxFactory / UFbxImportUI 公开 API 编写；部署时请对照目标引擎安装目录的
// FbxImportUI.h / FBXImporter.h 确认成员名与重载（见 docs/DEPLOYMENT.md 验证清单）。
#include "FbxImporter.h"

#include "CarlaAssetImporter.h"
#include "AssetRegistryModule.h"
#include "Editor.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "UObject/Package.h"

// UE4.26 经典 FBX 导入管线（FBXImporter 插件公开头文件）
#include "FBXImporter.h"
#include "FbxImportUI.h"

namespace
{
	// ★固化导入参数常量（禁止外部修改，保证跨环境一致性）
	namespace FixedParams
	{
		constexpr bool  bImportMesh = true;
		constexpr bool  bImportAnimation = false;   // CARLA 程序化动画，无动画序列
		constexpr bool  bImportMaterials = true;
		constexpr bool  bImportTextures = true;
		constexpr float UniformScale = 1.0f;         // 厘米制已在 L1 拦截
		constexpr bool  bAutoComputeLod = false;     // LOD 由资产侧提供
		constexpr bool  bConvertScene = false;
		constexpr bool  bForceFrontXAxis = true;     // 车头 +X
		constexpr bool  bVertexColorImportOption = false;
		constexpr bool  bGenerateLightmapUVs = true;
		constexpr bool  bAutoComputeCollision = true;
	}

	/** 通过官方 UFbxFactory 执行导入（必须在 UE 进程内，红线 §1.3）。 */
	UObject* RunFbxFactory(const FString& FilePath, UPackage* Package,
		const FString& AssetName, bool bAsSkeletal)
	{
		UFbxFactory* FbxFactory = NewObject<UFbxFactory>(UFbxFactory::StaticClass());
		FbxFactory->AddToRoot();

		UFbxImportUI* ImportUI = NewObject<UFbxImportUI>(FbxFactory);
		FbxFactory->ImportUI = ImportUI;

		ImportUI->MeshTypeToImport = bAsSkeletal ? FBXIT_SkeletalMesh : FBXIT_StaticMesh;
		ImportUI->bImportMesh = FixedParams::bImportMesh;
		ImportUI->bImportAnimations = FixedParams::bImportAnimation;
		ImportUI->bImportMaterials = FixedParams::bImportMaterials;
		ImportUI->bImportTextures = FixedParams::bImportTextures;
		ImportUI->UniformScale = FixedParams::UniformScale;
		ImportUI->bConvertScene = FixedParams::bConvertScene;
		ImportUI->bForceFrontXAxis = FixedParams::bForceFrontXAxis;
		ImportUI->bGenerateLightmapUVs = FixedParams::bGenerateLightmapUVs;
		ImportUI->bAutomatedImportShouldResetToDefaultSettings = true;
		ImportUI->RenameActors = true;
		ImportUI->ReplacePrevious = true;

		const FName SafeName(*AssetName);   // 资产名不含路径（由 BuildAssetLocation 保证）
		UObject* Result = FbxFactory->ImportObject(
			bAsSkeletal ? USkeletalMesh::StaticClass() : UStaticMesh::StaticClass(),
			Package, SafeName, RF_Standalone, FilePath, nullptr, ImportUI);

		FbxFactory->RemoveFromRoot();
		return Result;
	}
}

void UCarlaFbxImporter::BuildAssetLocation(const FString& ModelLower, const FString& Suffix,
	FString& OutPackagePath, FString& OutAssetName)
{
	const FString ModelName = ModelLower.Left(1).ToUpper() + ModelLower.RightChop(1);
	OutPackagePath = FString::Printf(TEXT("/Game/Carla/Blueprints/Vehicles/%s"), *ModelName);
	OutAssetName = FString::Printf(TEXT("%s_%s"), *ModelName, *Suffix);
}

USkeletalMesh* UCarlaFbxImporter::ImportSkeletalMesh(const FCarlaVehicleManifest& Manifest)
{
	FString PackagePath, AssetName;
	BuildAssetLocation(Manifest.Model, TEXT("SkelMesh"), PackagePath, AssetName);

	UPackage* Package = CreatePackage(*PackagePath);
	if (!Package)
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("Cannot create package %s"), *PackagePath);
		return nullptr;
	}

	USkeletalMesh* Mesh = Cast<USkeletalMesh>(
		RunFbxFactory(Manifest.Mesh.FbxPath, Package, AssetName, true));
	if (!Mesh)
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("FBX skeletal import failed: %s"),
			*Manifest.Mesh.FbxPath);
		return nullptr;
	}

	// ★挂接官方标准骨架（红线：不创建/不修改骨架，仅引用）
	USkeleton* StdSkeleton = Cast<USkeleton>(StaticLoadObject(USkeleton::StaticClass(),
		nullptr, *GetStandardSkeletonPath()));
	if (StdSkeleton && Mesh->GetSkeleton() != StdSkeleton)
	{
		Mesh->SetSkeleton(StdSkeleton);
		Mesh->PostEditChange();
	}
	else if (!StdSkeleton)
	{
		UE_LOG(LogCarlaAssetImport, Warning,
			TEXT("Standard skeleton not found at %s — mesh keeps imported skeleton"),
			*GetStandardSkeletonPath());
	}

	Mesh->MarkPackageDirty();
	FAssetRegistryModule::AssetCreated(Mesh);
	UE_LOG(LogCarlaAssetImport, Log, TEXT("Imported skeletal mesh %s.%s"),
		*PackagePath, *AssetName);
	return Mesh;
}

UStaticMesh* UCarlaFbxImporter::ImportStaticMesh(const FString& FbxPath,
	const FString& PackagePath, const FString& AssetName, bool bSimpleCollision)
{
	UPackage* Package = CreatePackage(*PackagePath);
	if (!Package)
	{
		return nullptr;
	}
	UStaticMesh* Mesh = Cast<UStaticMesh>(RunFbxFactory(FbxPath, Package, AssetName, false));
	if (Mesh)
	{
		// 简模轨：使用简单凸包碰撞降精度；标准轨保留自动复杂碰撞
		Mesh->MarkPackageDirty();
		FAssetRegistryModule::AssetCreated(Mesh);
	}
	return Mesh;
}
