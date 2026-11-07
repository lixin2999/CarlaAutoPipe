// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "AssetManifest.h"

/**
 * 地图导入与自动化编排（V1.4 §4.5 / V1.2 §4.6）。
 *
 * 阶段：FBX 导入 → XODR 路网绑定 → 材质适配（可关）→
 *       ★NavMesh 两阶段生成（车辆层 → 行人层，含异步加载等待保护）→ 关卡注册。
 */
class UCarlaMapImporter
{
public:
	struct FIssue
	{
		FString Level;
		FString Code;
		FString Message;
		FString Suggestion;
	};

	int32 ImportMap(const FCarlaMapManifest& Manifest, bool bDryRun);

	const TArray<FIssue>& GetIssues() const { return Issues; }

	/**
	 * ★异步等待保护：轮询 FStreamableManager 请求完成，并等待全部静态网格
	 * 物理Body初始化（碰撞就绪）后返回。避免行人网格在道具物理未生效前
	 * 生成导致穿帮。超时返回 false。
	 */
	static bool WaitForSceneReady(UWorld* World, float TimeoutSec = 120.f);

private:
	void LogIssue(const TCHAR* Level, const FString& Code, const FString& Msg,
		const FString& Suggestion = FString());
	bool ImportTerrain(const FCarlaMapManifest& Manifest);
	bool BindOpenDrive(const FCarlaMapManifest& Manifest);
	bool AdaptMaterials(const FCarlaMapManifest& Manifest);
	bool BuildNavMesh(const FCarlaMapManifest& Manifest, bool bPedestrianPass);
	bool RegisterLevel(const FCarlaMapManifest& Manifest);

	/** 反射写入 WorldSettings.NavigationSystemConfig.SupportedAgents 的 Agent 尺寸。 */
	static void ApplyAgentProfile(UWorld* World, float RadiusCM, float HeightCM, float ClimbCM);

	TArray<FIssue> Issues;
	TWeakObjectPtr<UWorld> LoadedWorld;
	FString LevelPackagePath;
};
