// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "Commandlets/Commandlet.h"
#include "CarlaAssetImportCommandlet.generated.h"

/**
 * CARLA 资产导入统一 Commandlet（V1.4 §3.1 / V1.2 §7.1）。
 *
 * 调用方式：
 *   UE4Editor-Cmd.exe CarlaUE4.uproject -run=CarlaAssetImport -mode=vehicle \
 *       -manifest=<path> [-dry-run] [-skip-factory] [-batch-size=N] \
 *       [-templatedir=<disk path>] [-report=<out.json>] \
 *       -stdout -unattended -nopause -nullrhi
 *
 * 退出码契约（与 Python CLI 一致）：
 *   0 SUCCESS / 1 ASSET_VALIDATION_FAIL / 2 ENGINE_INTERNAL_ERROR / 3 ENVIRONMENT_ERROR
 */
UCLASS()
class UCarlaAssetImportCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UCarlaAssetImportCommandlet();

	virtual int32 Main(const FString& Params) override;

private:
	int32 ProcessVehicle(const FString& ManifestPath);
	int32 ProcessMap(const FString& ManifestPath);

	/** 写出引擎侧统一 JSON 报告（GUI/CI 消费）。 */
	void WriteReportJson();

	// --- 命令行状态 ---
	FString Mode;
	FString ManifestArg;
	FString ReportPath;
	FString TemplateDirOverride;
	bool bDryRun = false;
	bool bSkipFactory = false;
	bool bSkipNavMesh = false;
	int32 BatchSize = 0;

	// --- 执行结果累加 ---
	struct FReportIssue
	{
		FString Level;   // ERROR / WARNING / INFO
		FString Code;
		FString Message;
		FString Suggestion;
	};
	TArray<FReportIssue> Issues;
	int32 ProcessedCount = 0;

	void LogIssue(const TCHAR* Level, const FString& Code, const FString& Msg,
		const FString& Suggestion = FString());
	bool HasErrors() const;

	/** ★防 OOM：显式垃圾回收（V1.4 §4.3），批处理每 BatchSize 个资产与主流程末尾调用。 */
	static void CollectGarbageExplicit();
};
