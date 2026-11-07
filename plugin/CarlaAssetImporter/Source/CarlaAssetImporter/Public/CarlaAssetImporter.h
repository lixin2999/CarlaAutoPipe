// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "Modules/ModuleManager.h"

DECLARE_LOG_CATEGORY_EXTERN(LogCarlaAssetImport, Log, All);

class FCarlaAssetImporterModule : public IModuleInterface
{
public:
	//~ Begin IModuleInterface
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
	//~ End IModuleInterface
};
