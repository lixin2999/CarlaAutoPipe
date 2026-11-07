// Copyright CarlaAutoPipe Team. All Rights Reserved.
using UnrealBuildTool;

public class CarlaAssetImporter : ModuleRules
{
	public CarlaAssetImporter(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"UnrealEd",        // UEditorEngine / 资产工厂 / FKismetEditorUtilities
			"AssetTools",      // IAssetTools::DuplicateAssets
			"KismetCompiler",  // 蓝图编译
			"Json",
			"JsonUtilities",
			"Projects",        // IPluginManager / IModuleManager
			"PhysicsCore",
			"SkeletonEditor",  // 物理资产编辑基础设施
			"NavigationSystem" // NavMesh 重建
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"FBXImporter",     // UFbxImportUI（UE4.26 经典 FBX 导入管线）
			"PropertyEditor",
			"Slate",
			"SlateCore",
			"DeveloperSettings"
		});

		// 说明：不直接依赖 Carla 运行时模块，ACarlaWheeledVehicle 等类型一律
		// 通过软对象路径 + 反射访问，避免插件与源码工程模块耦合（设计文档 §1.3）。
	}
}
