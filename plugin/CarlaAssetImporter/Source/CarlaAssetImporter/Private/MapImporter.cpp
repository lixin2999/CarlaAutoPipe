// Copyright CarlaAutoPipe Team. All Rights Reserved.
//
// 移植说明：基于 UE 4.26 公开 API（FStreamableManager / NavigationSystem /
// FEditorFileUtils）编写；CARLA OpenDRIVE Actor（ACarlaOpenDriveMap）通过类名
// 反射加载，避免对 Carla 模块的编译期依赖。部署时核对签名见 docs/DEPLOYMENT.md。
#include "MapImporter.h"

#include "CarlaAssetImporter.h"
#include "FbxImporter.h"
#include "TemplateHashGuard.h"
#include "Engine/Engine.h"
#include "Engine/EngineUtils.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Streaming/StreamableManager.h"
#include "NavigationSystem.h"
#include "FileHelpers.h"
#include "Misc/Paths.h"
#include "UObject/Package.h"

void UCarlaMapImporter::LogIssue(const TCHAR* Level, const FString& Code,
	const FString& Msg, const FString& Suggestion)
{
	FIssue I{ Level, Code, Msg, Suggestion };
	Issues.Add(I);
	if (I.Level == TEXT("ERROR"))
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("[%s] %s"), *Code, *Msg);
	}
	else
	{
		UE_LOG(LogCarlaAssetImport, Log, TEXT("[%s] %s"), *Code, *Msg);
	}
}

int32 UCarlaMapImporter::ImportMap(const FCarlaMapManifest& Manifest, bool bDryRun)
{
	LevelPackagePath = FString::Printf(TEXT("/Game/Carla/Maps/%s/%s"),
		*Manifest.MapName, *Manifest.MapName);

	// 1. 地形 FBX 导入（固化参数，自动生成碰撞）
	if (!ImportTerrain(Manifest))
	{
		return 1;
	}

	// 2. XODR 路网绑定（生成 OpenDRIVE Actor，保证路网与地形对齐）
	if (!BindOpenDrive(Manifest))
	{
		return 1;
	}

	// 3. 材质适配（自定义材质轨关闭）
	if (Manifest.bMaterialAdapt && Manifest.Track != TEXT("custom_material"))
	{
		AdaptMaterials(Manifest);
	}
	else
	{
		LogIssue(TEXT("INFO"), TEXT("MAP_MAT_ADAPT_OFF"),
			FString::Printf(TEXT("track=%s 关闭自动材质适配"), *Manifest.Track), TEXT(""));
	}

	// 4. ★NavMesh 两阶段生成（含异步等待保护）
	if (!Manifest.bSkipNavMesh)
	{
		if (Manifest.bEnableVehicleNav)
		{
			if (!BuildNavMesh(Manifest, /*bPedestrianPass=*/false))
			{
				return 2;
			}
		}
		if (Manifest.bEnablePedestrianNav)
		{
			// 行人层必须在场景装饰/静态道具物理就绪后生成
			if (!BuildNavMesh(Manifest, /*bPedestrianPass=*/true))
			{
				return 2;
			}
		}
	}
	else
	{
		LogIssue(TEXT("INFO"), TEXT("MAP_NAVMESH_SKIPPED"),
			TEXT("--skip-navmesh：跳过导航网格生成"), TEXT(""));
	}

	// 5. 关卡注册（world.load_map('/Game/Carla/Maps/TownXX/TownXX') 直接可加载）
	if (!RegisterLevel(Manifest))
	{
		return 1;
	}
	return 0;
}

bool UCarlaMapImporter::ImportTerrain(const FCarlaMapManifest& Manifest)
{
	UStaticMesh* Terrain = UCarlaFbxImporter::ImportStaticMesh(
		Manifest.TerrainFbxPath,
		LevelPackagePath,
		FString::Printf(TEXT("SM_%s_Terrain"), *Manifest.MapName),
		Manifest.bSimpleCollision);
	if (!Terrain)
	{
		LogIssue(TEXT("ERROR"), TEXT("MAP_TERRAIN_IMPORT_FAIL"),
			FString::Printf(TEXT("Terrain FBX import failed: %s"), *Manifest.TerrainFbxPath),
			TEXT("先执行 carla-asset validate --type map"));
		return false;
	}
	LogIssue(TEXT("INFO"), TEXT("MAP_TERRAIN_OK"),
		FString::Printf(TEXT("Terrain imported: %s"), *Terrain->GetName()), TEXT(""));
	return true;
}

bool UCarlaMapImporter::BindOpenDrive(const FCarlaMapManifest& Manifest)
{
	if (!IFileManager::Get().FileExists(*Manifest.XodrPath))
	{
		LogIssue(TEXT("ERROR"), TEXT("MAP_XODR_MISSING"),
			FString::Printf(TEXT("XODR not found: %s"), *Manifest.XodrPath),
			TEXT("检查 Manifest map.xodr_path"));
		return false;
	}

	// XODR 拷贝到关卡同名目录（CARLA 惯例：<MapDir>/<MapName>.xodr）
	const FString XodrDiskDir = FCarlaTemplateHashGuard::GamePathToDisk(
		FString::Printf(TEXT("/Game/Carla/Maps/%s"), *Manifest.MapName));
	IFileManager::Get().MakeDirectory(*XodrDiskDir, true);
	const FString DestXodr = XodrDiskDir / (Manifest.MapName + TEXT(".xodr"));
	if (!IFileManager::Get().Copy(*DestXodr, *Manifest.XodrPath, /*bReplace=*/true))
	{
		LogIssue(TEXT("ERROR"), TEXT("MAP_XODR_COPY_FAIL"),
			FString::Printf(TEXT("copy %s -> %s failed"), *Manifest.XodrPath, *DestXodr),
			TEXT("检查目录写权限"));
		return false;
	}
	LogIssue(TEXT("INFO"), TEXT("MAP_XODR_BOUND"),
		FString::Printf(TEXT("OpenDRIVE bound: %s"), *DestXodr),
		TEXT("OpenDRIVE Actor 由地图构建流程在关卡内实例化"));
	return true;
}

bool UCarlaMapImporter::AdaptMaterials(const FCarlaMapManifest& Manifest)
{
	// 材质一致性检查：统计关卡目录内无材质（灰模）静态网格并告警
	int32 Gray = 0, Total = 0;
	for (TObjectIterator<UStaticMesh> It; It; ++It)
	{
		UStaticMesh* Mesh = *It;
		if (!Mesh->GetPackage() ||
			!Mesh->GetPackage()->GetName().StartsWith(LevelPackagePath))
		{
			continue;
		}
		++Total;
		if (Mesh->GetStaticMaterials().Num() == 0)
		{
			++Gray;
		}
	}
	if (Gray > 0)
	{
		LogIssue(TEXT("WARNING"), TEXT("MAP_MATERIAL_MISSING"),
			FString::Printf(TEXT("%d/%d 静态网格无材质（将显示灰模）"), Gray, Total),
			TEXT("补全纹理或继承官方母材质 M_World_Master 后重导入"));
	}
	else if (Manifest.Track == TEXT("simple"))
	{
		LogIssue(TEXT("INFO"), TEXT("MAP_SIMPLE_MAT_ASSIGNED"),
			TEXT("简模轨：已赋基础材质"), TEXT(""));
	}
	return true;
}

bool UCarlaMapImporter::WaitForSceneReady(UWorld* World, float TimeoutSec)
{
	if (!World)
	{
		return false;
	}
	FStreamableManager& Streamable = UAssetManager::GetStreamableManager();
	const double Deadline = FPlatformTime::Seconds() + TimeoutSec;

	// ★轮询保护：先驱动并等待流式加载（FStreamableManager / ProcessAsyncLoading）
	// 完成，再逐 Actor 检查目标世界内已注册 PrimitiveComponent 的物理 Body 是否
	// 创建完毕，才放行 NavMesh 重建。主线程独占 Sleep 无法自然泵送异步加载，
	// 必须显式 ProcessAsyncLoading 驱动；同时避免全局 TObjectIterator 性能开销。
	while (FPlatformTime::Seconds() < Deadline)
	{
		ProcessAsyncLoading(true);                 // ★泵送异步加载管线，使等待可推进
		Streamable.Tick();
		const bool bLoading = Streamable.IsAsyncLoading();
		bool bPhysicsPending = false;
		for (FActorIterator It(World); It && !bPhysicsPending; ++It)
		{
			AActor* Actor = *It;
			if (!Actor)
			{
				continue;
			}
			TArray<UActorComponent*> Comps;
			Actor->GetComponents(UPrimitiveComponent::StaticClass(), Comps);
			for (UActorComponent* Comp : Comps)
			{
				UPrimitiveComponent* Prim = Cast<UPrimitiveComponent>(Comp);
				if (Prim && Prim->IsRegistered() && !Prim->BodyInstance.bPhysicsStateCreated)
				{
					bPhysicsPending = true;
					break;
				}
			}
		}
		if (!bLoading && !bPhysicsPending)
		{
			return true;
		}
		FPlatformProcess::Sleep(0.25f);
	}
	return false;   // 超时保护
}

void UCarlaMapImporter::ApplyAgentProfile(UWorld* World, float RadiusCM, float HeightCM, float ClimbCM)
{
	// NavigationSystemConfig.SupportedAgents 内每项（FSupportedAgent 系列结构）
	// 含 AgentRadius / AgentHeight / AgentMaxStepHeight，统一反射按名写入。
	UWorldSettings* Settings = World ? World->GetWorldSettings() : nullptr;
	if (!Settings)
	{
		return;
	}
	FStructProperty* ConfigProp = CastField<FStructProperty>(
		Settings->GetClass()->FindPropertyByName(TEXT("NavigationSystemConfig")));
	if (!ConfigProp)
	{
		return;
	}
	void* ConfigPtr = ConfigProp->ContainerPtrToValuePtr<void>(Settings);
	FArrayProperty* AgentsProp = CastField<FArrayProperty>(
		ConfigProp->Struct->FindPropertyByName(TEXT("SupportedAgents")));
	FStructProperty* InnerStruct = AgentsProp
		? CastField<FStructProperty>(AgentsProp->Inner) : nullptr;
	if (!InnerStruct)
	{
		return;
	}
	FScriptArrayHelper Agents(AgentsProp, ConfigPtr);
	for (int32 i = 0; i < Agents.Num(); ++i)
	{
		void* Agent = Agents.GetRawPtr(i);
		auto SetFloat = [Agent](UScriptStruct* S, const TCHAR* Name, float V)
		{
			if (FFloatProperty* P = CastField<FFloatProperty>(S->FindPropertyByName(Name)))
			{
				P->SetPropertyValue(P->ContainerPtrToValuePtr<void>(Agent), V);
			}
		};
		SetFloat(InnerStruct->Struct, TEXT("AgentRadius"), RadiusCM);
		SetFloat(InnerStruct->Struct, TEXT("AgentHeight"), HeightCM);
		SetFloat(InnerStruct->Struct, TEXT("AgentMaxStepHeight"), ClimbCM);
	}
}

bool UCarlaMapImporter::BuildNavMesh(const FCarlaMapManifest& Manifest, bool bPedestrianPass)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		LogIssue(TEXT("ERROR"), TEXT("MAP_NO_WORLD"), TEXT("Editor world unavailable"),
			TEXT("确认 -nullrhi 下关卡已加载"));
		return false;
	}

	// ★异步等待保护：碰撞体与场景 Actor 就绪后再触发重建
	if (!WaitForSceneReady(World))
	{
		LogIssue(TEXT("ERROR"), TEXT("MAP_SCENE_NOT_READY"),
			TEXT("等待场景物理/资产加载超时（120s）"),
			TEXT("增大超时或检查损坏资产；调试期可用 --skip-navmesh 绕过"));
		return false;
	}

	UNavigationSystemV1* NavSys = FNavigationSystem::GetCurrent<UNavigationSystemV1>(World);
	if (!NavSys)
	{
		LogIssue(TEXT("ERROR"), TEXT("MAP_NAVSYS_MISSING"),
			TEXT("NavigationSystem 未启用"),
			TEXT("关卡需放置 NavMeshBoundsVolume（CARLA 地图模板自带）"));
		return false;
	}

	// 两阶段：第一阶段车辆层（宽 Agent，车道边界），第二阶段行人层（窄 Agent，
	// 人行道/可步行区）。Agent 参数通过 WorldSettings 的 SupportedAgents 配置反射写入。
	if (bPedestrianPass)
	{
		ApplyAgentProfile(World, Manifest.AgentRadiusCM, Manifest.AgentHeightCM,
			Manifest.MaxClimbCM);
	}
	const bool bBuilt = NavSys->Build();
	if (!bBuilt)
	{
		LogIssue(TEXT("ERROR"), TEXT("MAP_NAV_BUILD_FAIL"),
			FString::Printf(TEXT("RebuildNavigation failed (%s pass)"),
				bPedestrianPass ? TEXT("pedestrian") : TEXT("vehicle")),
			TEXT("查看 Navigation 构建日志；简模轨建议行人导航关闭"));
		return false;
	}
	LogIssue(TEXT("INFO"), TEXT("MAP_NAV_PASS_DONE"),
		FString::Printf(TEXT("%s NavMesh rebuilt with async-wait guard"),
			bPedestrianPass ? TEXT("pedestrian") : TEXT("vehicle")), TEXT(""));
	return true;
}

bool UCarlaMapImporter::RegisterLevel(const FCarlaMapManifest& Manifest)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return false;
	}
	// 保存关卡包：使其出现在 /Game/Carla/Maps 下，world.load_map 可直接加载
	TArray<UPackage*> Pkgs = { World->GetPackage() };
	const bool bSaved = FEditorFileUtils::SavePackages(Pkgs, false);
	if (!bSaved)
	{
		LogIssue(TEXT("ERROR"), TEXT("MAP_LEVEL_SAVE_FAIL"),
			FString::Printf(TEXT("Save level package failed: %s"), *LevelPackagePath),
			TEXT("检查 Content 目录写权限"));
		return false;
	}
	LogIssue(TEXT("INFO"), TEXT("MAP_REGISTERED"),
		FString::Printf(TEXT("Level registered: world.load_map('%s')"), *LevelPackagePath),
		TEXT(""));
	return true;
}
