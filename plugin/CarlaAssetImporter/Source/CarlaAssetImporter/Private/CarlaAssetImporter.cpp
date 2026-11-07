// Copyright CarlaAutoPipe Team. All Rights Reserved.
#include "CarlaAssetImporter.h"

DEFINE_LOG_CATEGORY(LogCarlaAssetImport);

#define LOCTEXT_NAMESPACE "FCarlaAssetImporterModule"

void FCarlaAssetImporterModule::StartupModule()
{
	UE_LOG(LogCarlaAssetImport, Log, TEXT("CARLA Asset Importer plugin loaded (V1.0.0)"));
}

void FCarlaAssetImporterModule::ShutdownModule()
{
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FCarlaAssetImporterModule, CarlaAssetImporter)
