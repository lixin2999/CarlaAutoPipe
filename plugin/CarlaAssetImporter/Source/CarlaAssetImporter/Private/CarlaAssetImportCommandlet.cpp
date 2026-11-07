// Copyright CarlaAutoPipe Team. All Rights Reserved.
#include "CarlaAssetImportCommandlet.h"

#include "CarlaAssetImporter.h"
#include "AssetManifest.h"
#include "TemplateHashGuard.h"
#include "FbxImporter.h"
#include "GoldenTemplateCopier.h"
#include "VehiclePhysicsBuilder.h"
#include "VehicleBlueprintAssembler.h"
#include "VehicleFactoryRegistrar.h"
#include "MapImporter.h"

#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Serialization/JsonWriter.h"
#include "Serialization/JsonSerializer.h"
#include "Dom/JsonObject.h"
#include "UObject/Package.h"

UCarlaAssetImportCommandlet::UCarlaAssetImportCommandlet()
{
	IsClient = false;
	IsEditor = true;
	LogToConsole = true;
}

void UCarlaAssetImportCommandlet::LogIssue(const TCHAR* Level, const FString& Code,
	const FString& Msg, const FString& Suggestion)
{
	FReportIssue Issue;
	Issue.Level = Level;
	Issue.Code = Code;
	Issue.Message = Msg;
	Issue.Suggestion = Suggestion;
	Issues.Add(MoveTemp(Issue));

	if (Issue.Level == TEXT("ERROR"))
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("[%s] %s"), *Code, *Msg);
	}
	else if (Issue.Level == TEXT("WARNING"))
	{
		UE_LOG(LogCarlaAssetImport, Warning, TEXT("[%s] %s"), *Code, *Msg);
	}
	else
	{
		UE_LOG(LogCarlaAssetImport, Log, TEXT("[%s] %s"), *Code, *Msg);
	}
}

bool UCarlaAssetImportCommandlet::HasErrors() const
{
	return Issues.ContainsByPredicate(
		[](const FReportIssue& I) { return I.Level == TEXT("ERROR"); });
}

void UCarlaAssetImportCommandlet::CollectGarbageExplicit()
{
	// ★显式清理与垃圾回收（V1.4 §4.3）：防止 Headless 编辑器批量导入堆积 OOM
	CollectGarbage(GARBAGE_COLLECTION_KEEPFLAGS);
	FCoreUObjectDelegates::PostGarbageCollect.Broadcast();
}

int32 UCarlaAssetImportCommandlet::Main(const FString& Params)
{
	// ---- 参数解析 ----------------------------------------------------------
	TArray<FString> Tokens;
	TArray<FString> Switches;
	ParseCommandLine(*Params, Tokens, Switches);
	FParse::Value(*Params, TEXT("-manifest="), ManifestArg);
	FParse::Value(*Params, TEXT("-mode="), Mode);
	FParse::Value(*Params, TEXT("-report="), ReportPath);
	FParse::Value(*Params, TEXT("-templatedir="), TemplateDirOverride);
	bDryRun = Switches.Contains(TEXT("DRY-RUN"));
	bSkipFactory = Switches.Contains(TEXT("SKIP-FACTORY")) || Switches.Contains(TEXT("SKIP_FACTORY"));
	bSkipNavMesh = Switches.Contains(TEXT("SKIP-NAVMESH")) || Switches.Contains(TEXT("SKIP_NAVMESH"));
	FString BatchStr;
	if (FParse::Value(*Params, TEXT("-batch-size="), BatchStr))
	{
		BatchSize = FCString::Atoi(*BatchStr);
	}

	int32 RetCode = 0;
	if (ManifestArg.IsEmpty())
	{
		LogIssue(TEXT("ERROR"), TEXT("CMD_MANIFEST_MISSING"),
			TEXT("-manifest=<path> is required"),
			TEXT("carla-asset build-vehicle --manifest=manifests/vehicles/<x>.json"));
		RetCode = 1;
	}
	else if (Mode == TEXT("vehicle"))
	{
		RetCode = ProcessVehicle(ManifestArg);
	}
	else if (Mode == TEXT("map"))
	{
		RetCode = ProcessMap(ManifestArg);
	}
	else
	{
		LogIssue(TEXT("ERROR"), TEXT("CMD_MODE_UNKNOWN"),
			FString::Printf(TEXT("Unknown mode '%s' (expect vehicle|map)"), *Mode), TEXT(""));
		RetCode = 1;
	}

	// ---- 收尾：刷新事务队列 + 显式 GC + 报告 --------------------------------
	// ★延迟编译事务队列在批处理末尾统一 CompileBlueprint（V1.4 §4.4）
	UVehicleFactoryRegistrar::FlushPendingRegistrations(bDryRun);
	CollectGarbageExplicit();

	if (RetCode == 0 && HasErrors())
	{
		RetCode = 1;
	}
	WriteReportJson();
	UE_LOG(LogCarlaAssetImport, Log, TEXT("CarlaAssetImport finished: mode=%s code=%d issues=%d"),
		*Mode, RetCode, Issues.Num());
	return RetCode;
}

int32 UCarlaAssetImportCommandlet::ProcessVehicle(const FString& ManifestPath)
{
	FCarlaVehicleManifest Manifest;
	FString Error;
	if (!FCarlaAssetManifestLoader::LoadVehicle(ManifestPath, Manifest, Error))
	{
		LogIssue(TEXT("ERROR"), TEXT("MFT_VEHICLE_FAIL"), Error,
			TEXT("对照 schemas/vehicle.schema.json 修正"));
		return 1;
	}

	// ---- ★黄金模板绝对哈希卡点（V1.4 §4.3）：Manifest 校验后、复制前 --------
	const FString TemplateDiskDir = TemplateDirOverride.IsEmpty()
		? FCarlaTemplateHashGuard::GamePathToDisk(
			TEXT("/Game/Carla/Blueprints/Vehicles/_Template"))
		: TemplateDirOverride;
	FString ActualHash;
	if (!FCarlaTemplateHashGuard::ComputeDirectoryDigest(TemplateDiskDir, ActualHash))
	{
		LogIssue(TEXT("ERROR"), TEXT("TPL_DIR_MISSING"),
			FString::Printf(TEXT("Golden template directory not found: %s"), *TemplateDiskDir),
			TEXT("配置 -templatedir= 或部署官方 _Template 目录"));
		return 3;   // ENVIRONMENT_ERROR
	}
	if (!ActualHash.Equals(Manifest.GoldenTemplateChecksum, ESearchCase::IgnoreCase))
	{
		LogIssue(TEXT("ERROR"), TEXT("TPL_HASH_MISMATCH"),
			FString::Printf(TEXT("Golden template SHA-256 mismatch: expected=%s actual=%s"),
				*Manifest.GoldenTemplateChecksum, *ActualHash),
			TEXT("恢复模板目录原始内容，或确认合法后更新 Manifest golden_template_checksum"));
		return 3;   // ENVIRONMENT_ERROR —— 绝对卡点，防止误改模板导致连锁问题
	}
	UE_LOG(LogCarlaAssetImport, Log, TEXT("Golden template hash OK: %s"), *ActualHash);

	if (bDryRun)
	{
		LogIssue(TEXT("INFO"), TEXT("BUILD_DRY_RUN"),
			TEXT("dry-run: manifest & template checks passed, nothing saved"), TEXT(""));
		return 0;
	}

	// ---- 车辆管线编排（V1.2 §7.1 骨架） --------------------------------------
	// 1. 导入 FBX 骨骼网格体（固化参数）
	USkeletalMesh* SkelMesh = UCarlaFbxImporter::ImportSkeletalMesh(Manifest);
	if (!SkelMesh)
	{
		LogIssue(TEXT("ERROR"), TEXT("FBX_IMPORT_FAIL"),
			FString::Printf(TEXT("Skeletal mesh import failed for %s"), *Manifest.Mesh.FbxPath),
			TEXT("先运行 carla-asset validate/rig 完成资产合规化"));
		return 1;
	}

	// 2. 构建物理资产
	UPhysicsAsset* PhysAsset = UCarlaVehiclePhysicsBuilder::Build(SkelMesh, Manifest);
	if (!PhysAsset)
	{
		LogIssue(TEXT("ERROR"), TEXT("PHYSICS_BUILD_FAIL"),
			TEXT("Physics asset construction failed"),
			TEXT("检查骨骼命名与 Manifest physics_asset 配置"));
		return 2;
	}

	// 3. 黄金模板复制 + 引用改写（AnimBP / 前后轮 BP / VehicleBP）
	FGuid BatchId = FGuid::NewGuid();
	UBlueprint* VehicleBP = UCarlaGoldenTemplateCopier::DuplicateAndAssemble(
		Manifest, SkelMesh, PhysAsset, BatchId);
	if (!VehicleBP)
	{
		LogIssue(TEXT("ERROR"), TEXT("TEMPLATE_DUP_FAIL"),
			TEXT("Golden template duplication/retarget failed"),
			TEXT("确认 _Template 目录完整（AnimBP/前后轮BP/VehicleBP 一套）"));
		return 2;
	}

	// 4. VehicleFactory 注册（通道 A；--skip-factory 时走通道 B 由运行端按路径加载）
	if (!Manifest.Registration.bSkipFactory && !bSkipFactory)
	{
		// ★入队而非即时编译 —— 批处理末尾统一 Flush（V1.4 §4.4）
		UCarlaVehicleFactoryRegistrar::EnqueueRegistration(Manifest, VehicleBP, bDryRun);
	}
	else
	{
		LogIssue(TEXT("INFO"), TEXT("FACTORY_SKIPPED"),
			FString::Printf(TEXT("%s 走降级通道 B：运行端按资产路径直接加载"),
				*Manifest.GetAssetId()),
			TEXT("通道 B 不支持 filter 检索与 ScenarioRunner model= 匹配，正式流程请走通道 A"));
	}

	// 5. 保存（VehicleFactory 最后保存，由 FlushPendingRegistrations 保证）
	if (!UCarlaGoldenTemplateCopier::SaveGeneratedAssets())
	{
		LogIssue(TEXT("ERROR"), TEXT("ASSET_SAVE_FAIL"),
			TEXT("Asset save to disk failed"), TEXT("检查 Content 目录写权限"));
		return 2;
	}

	ProcessedCount++;
	if (BatchSize > 0 && ProcessedCount % BatchSize == 0)
	{
		// ★分片 GC 防 OOM
		CollectGarbageExplicit();
	}
	UE_LOG(LogCarlaAssetImport, Log, TEXT("Vehicle pipeline finished for %s"),
		*Manifest.GetAssetId());
	return 0;
}

int32 UCarlaAssetImportCommandlet::ProcessMap(const FString& ManifestPath)
{
	FCarlaMapManifest Manifest;
	FString Error;
	if (!FCarlaAssetManifestLoader::LoadMap(ManifestPath, Manifest, Error))
	{
		LogIssue(TEXT("ERROR"), TEXT("MFT_MAP_FAIL"), Error,
			TEXT("对照 schemas/map.schema.json 修正"));
		return 1;
	}
	Manifest.bSkipNavMesh = bSkipNavMesh || Manifest.bSkipNavMesh;

	if (bDryRun)
	{
		LogIssue(TEXT("INFO"), TEXT("BUILD_DRY_RUN"),
			FString::Printf(TEXT("dry-run: map %s manifest passed"), *Manifest.MapName), TEXT(""));
		return 0;
	}

	UCarlaMapImporter Importer;
	const int32 Ret = Importer.ImportMap(Manifest, bDryRun);
	if (Ret != 0)
	{
		for (const FCarlaMapImporter::FIssue& I : Importer.GetIssues())
		{
			LogIssue(*I.Level, I.Code, I.Message, I.Suggestion);
		}
		return Ret;
	}
	ProcessedCount++;
	return 0;
}

void UCarlaAssetImportCommandlet::WriteReportJson()
{
	if (ReportPath.IsEmpty())
	{
		return;
	}
	TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("command"), FString::Printf(TEXT("build-%s"), *Mode));
	Root->SetNumberField(TEXT("exit_code"), HasErrors() ? 1 : 0);
	Root->SetStringField(TEXT("schema_version"), TEXT("1.0"));

	TArray<TSharedPtr<FJsonValue>> IssueArr;
	for (const FReportIssue& I : Issues)
	{
		TSharedPtr<FJsonObject> IObj = MakeShared<FJsonObject>();
		IObj->SetStringField(TEXT("level"), I.Level);
		IObj->SetStringField(TEXT("code"), I.Code);
		IObj->SetStringField(TEXT("message"), I.Message);
		IObj->SetStringField(TEXT("suggestion"), I.Suggestion);
		IssueArr.Add(MakeShared<FJsonValueObject>(IObj));
	}
	Root->SetArrayField(TEXT("issues"), IssueArr);
	Root->SetNumberField(TEXT("processed"), ProcessedCount);

	FString OutStr;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&OutStr);
	if (FJsonSerializer::Serialize(Root.ToSharedRef(), Writer))
	{
		FFileHelper::SaveStringToFile(OutStr, *ReportPath,
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	}
}
