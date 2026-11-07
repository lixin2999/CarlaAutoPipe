// Copyright CarlaAutoPipe Team. All Rights Reserved.
#include "AssetManifest.h"

#include "CarlaAssetImporter.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "FileHelpers.h"

namespace
{
	bool ReadJsonFile(const FString& Path, TSharedRef<FJsonObject>& OutObj, FString& OutError)
	{
		FString Raw;
		if (!FFileHelper::LoadFileToString(Raw, *Path))
		{
			OutError = FString::Printf(TEXT("Manifest file not found or unreadable: %s"), *Path);
			return false;
		}
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Raw);
		if (!FJsonSerializer::Deserialize(Reader, OutObj) || OutObj.IsNull())
		{
			OutError = FString::Printf(TEXT("Manifest JSON parse error: %s"), *Path);
			return false;
		}
		return true;
	}

	FString ToLowerTrim(const FString& V)
	{
		FString Out = V;
		Out.TrimStartAndEndInline();
		return Out.ToLower();
	}

	/** 工程纪律：make/model 强制全小写（V1.2 §6.4）。 */
	bool CheckIdentity(const TSharedPtr<FJsonObject>& Obj, FString& OutError)
	{
		FString Make, Model;
		Obj->TryGetStringField(TEXT("make"), Make);
		Obj->TryGetStringField(TEXT("model"), Model);
		if (Make.IsEmpty() || Model.IsEmpty())
		{
			OutError = TEXT("vehicle.make / vehicle.model must not be empty");
			return false;
		}
		int32 Wheels = 4;
		Obj->TryGetNumberField(TEXT("wheels"), Wheels);
		if (Wheels != 2 && Wheels != 4)
		{
			OutError = FString::Printf(
				TEXT("wheels must be 2 or 4 (red line: multi-axle vehicles not supported), got %d"),
				Wheels);
			return false;
		}
		FString Parent;
		if (Obj->HasField(TEXT("__blueprint_parent")))
		{
			// registration 子对象由调用方注入，此处仅防御性校验
		}
		return true;
	}
}

bool FCarlaAssetManifestLoader::LoadVehicle(const FString& Path,
	FCarlaVehicleManifest& Out, FString& OutError)
{
	TSharedRef<FJsonObject> Root;
	if (!ReadJsonFile(Path, Root, OutError))
	{
		return false;
	}
	Out.SourceManifestPath = Path;

	TSharedPtr<FJsonObject> V = Root->GetObjectField(TEXT("vehicle"));
	if (!V.IsValid())
	{
		OutError = TEXT("Missing \"vehicle\" object");
		return false;
	}
	Root->TryGetStringField(TEXT("target_carla"), Out.TargetCarla);
	if (Out.TargetCarla != TEXT("0.9.16"))
	{
		OutError = FString::Printf(
			TEXT("target_carla=%s unsupported, this tool targets 0.9.16 only"),
			*Out.TargetCarla);
		return false;
	}
	if (!CheckIdentity(V.ToSharedRef(), OutError))
	{
		return false;
	}
	V->TryGetStringField(TEXT("make"), Out.Make);
	V->TryGetStringField(TEXT("model"), Out.Model);
	V->TryGetStringField(TEXT("class"), Out.Class);
	V->TryGetStringField(TEXT("base_type"), Out.BaseType);
	Out.Make = ToLowerTrim(Out.Make);
	Out.Model = ToLowerTrim(Out.Model);
	double Dbl = 1;
	if (V->TryGetNumberField(TEXT("generation"), Dbl)) { Out.Generation = FMath::Clamp((int32)Dbl, 1, 3); }
	if (V->TryGetNumberField(TEXT("wheels"), Dbl)) { Out.Wheels = (int32)Dbl; }

	if (const TSharedPtr<FJsonObject>* MeshObj = nullptr; V->TryGetObjectField(TEXT("mesh"), MeshObj))
	{
		(*MeshObj)->TryGetStringField(TEXT("unit"), Out.Mesh.Unit);
		(*MeshObj)->TryGetStringField(TEXT("forward_axis"), Out.Mesh.ForwardAxis);
		(*MeshObj)->TryGetStringField(TEXT("up_axis"), Out.Mesh.UpAxis);
		(*MeshObj)->TryGetStringField(TEXT("fbx_path"), Out.Mesh.FbxPath);
	}
	// 红线：单位与轴向必须声明为 cm / +X / +Z
	if (Out.Mesh.Unit != TEXT("cm") || Out.Mesh.ForwardAxis != TEXT("+X") || Out.Mesh.UpAxis != TEXT("+Z"))
	{
		OutError = FString::Printf(TEXT("mesh contract violated: unit=%s forward=%s up=%s (require cm/+X/+Z)"),
			*Out.Mesh.Unit, *Out.Mesh.ForwardAxis, *Out.Mesh.UpAxis);
		return false;
	}

	if (const TSharedPtr<FJsonObject>* Ph = nullptr; V->TryGetObjectField(TEXT("physics_asset"), Ph))
	{
		(*Ph)->TryGetStringField(TEXT("body_type"), Out.Physics.BodyType);
		(*Ph)->TryGetStringField(TEXT("wheel_primitive"), Out.Physics.WheelPrimitive);
		(*Ph)->TryGetStringField(TEXT("wheel_physics_type"), Out.Physics.WheelPhysicsType);
		(*Ph)->TryGetBoolField(TEXT("generate_hit_events"), Out.Physics.bGenerateHitEvents);
		if ((*Ph)->TryGetNumberField(TEXT("shape_radius_m"), Dbl)) { Out.Physics.ShapeRadiusM = (float)Dbl; }
		if ((*Ph)->TryGetNumberField(TEXT("mass_kg"), Dbl)) { Out.Physics.MassKg = (float)Dbl; }
		if (const TSharedPtr<FJsonObject>* Com = nullptr; (*Ph)->TryGetObjectField(TEXT("center_of_mass"), Com))
		{
			double X = 0, Y = 0, Z = 0;
			(*Com)->TryGetNumberField(TEXT("x"), X);
			(*Com)->TryGetNumberField(TEXT("y"), Y);
			(*Com)->TryGetNumberField(TEXT("z"), Z);
			Out.Physics.CenterOfMass = FVector(X, Y, Z) * 100.0; // m -> cm
		}
	}

	if (const TArray<TSharedPtr<FJsonValue>>* Colors = nullptr;
		V->TryGetArrayField(TEXT("colors"), Colors))
	{
		for (const TSharedPtr<FJsonValue>& C : *Colors)
		{
			const TSharedPtr<FJsonObject>& CO = C->AsObject();
			if (CO.IsValid())
			{
				double R = 255, G = 255, B = 255, A = 255;
				CO->TryGetNumberField(TEXT("r"), R);
				CO->TryGetNumberField(TEXT("g"), G);
				CO->TryGetNumberField(TEXT("b"), B);
				CO->TryGetNumberField(TEXT("a"), A);
				Out.Colors.Add(FLinearColor(R / 255.0, G / 255.0, B / 255.0, A / 255.0));
			}
		}
	}

	if (const TSharedPtr<FJsonObject>* Reg = nullptr; Root->TryGetObjectField(TEXT("registration"), Reg))
	{
		(*Reg)->TryGetStringField(TEXT("vehicle_factory_path"), Out.Registration.VehicleFactoryPath);
		(*Reg)->TryGetStringField(TEXT("blueprint_parent"), Out.Registration.BlueprintParent);
		(*Reg)->TryGetBoolField(TEXT("skip_factory"), Out.Registration.bSkipFactory);
	}
	// 红线：车辆蓝图父类必须为 BaseVehiclePawn（V1.4 附录）
	if (Out.Registration.BlueprintParent != TEXT("BaseVehiclePawn"))
	{
		OutError = FString::Printf(TEXT("REDLINE: blueprint_parent must be BaseVehiclePawn, got %s"),
			*Out.Registration.BlueprintParent);
		return false;
	}
	Root->TryGetStringField(TEXT("golden_template_checksum"), Out.GoldenTemplateChecksum);
	if (Out.GoldenTemplateChecksum.Len() != 64)
	{
		OutError = TEXT("golden_template_checksum must be a 64-hex-digit SHA-256 digest");
		return false;
	}

	UE_LOG(LogCarlaAssetImport, Log, TEXT("Vehicle manifest loaded: %s (wheels=%d gen=%d)"),
		*Out.GetAssetId(), Out.Wheels, Out.Generation);
	return true;
}

bool FCarlaAssetManifestLoader::LoadMap(const FString& Path,
	FCarlaMapManifest& Out, FString& OutError)
{
	TSharedRef<FJsonObject> Root;
	if (!ReadJsonFile(Path, Root, OutError))
	{
		return false;
	}
	Out.SourceManifestPath = Path;

	TSharedPtr<FJsonObject> M = Root->GetObjectField(TEXT("map"));
	if (!M.IsValid())
	{
		OutError = TEXT("Missing \"map\" object");
		return false;
	}
	Root->TryGetStringField(TEXT("target_carla"), Out.TargetCarla);
	M->TryGetStringField(TEXT("map_name"), Out.MapName);
	M->TryGetStringField(TEXT("track"), Out.Track);
	M->TryGetStringField(TEXT("xodr_path"), Out.XodrPath);
	M->TryGetStringField(TEXT("terrain_fbx_path"), Out.TerrainFbxPath);
	M->TryGetStringField(TEXT("texture_dir"), Out.TextureDir);
	M->TryGetBoolField(TEXT("material_adapt"), Out.bMaterialAdapt);
	M->TryGetBoolField(TEXT("simple_collision"), Out.bSimpleCollision);
	if (Out.MapName.IsEmpty() || Out.XodrPath.IsEmpty() || Out.TerrainFbxPath.IsEmpty())
	{
		OutError = TEXT("map_name / xodr_path / terrain_fbx_path are all required");
		return false;
	}
	// XODR 与 FBX 主文件名一致性（ERROR 左移兜底）
	if (FPaths::GetCleanFilename(Out.XodrPath).Replace(TEXT(".xodr"), TEXT(""), ESearchCase::IgnoreCase)
		!= FPaths::GetCleanFilename(Out.TerrainFbxPath).Replace(TEXT(".fbx"), TEXT(""), ESearchCase::IgnoreCase))
	{
		OutError = FString::Printf(TEXT("XODR(%s) and terrain FBX(%s) base names must match"),
			*Out.XodrPath, *Out.TerrainFbxPath);
		return false;
	}
	if (const TSharedPtr<FJsonObject>* Nav = nullptr; M->TryGetObjectField(TEXT("navmesh_settings"), Nav))
	{
		(*Nav)->TryGetBoolField(TEXT("enable_vehicle_nav"), Out.bEnableVehicleNav);
		(*Nav)->TryGetBoolField(TEXT("enable_pedestrian_nav"), Out.bEnablePedestrianNav);
		double D = 30;
		if ((*Nav)->TryGetNumberField(TEXT("agent_radius_cm"), D)) { Out.AgentRadiusCM = (float)D; }
		if ((*Nav)->TryGetNumberField(TEXT("agent_height_cm"), D)) { Out.AgentHeightCM = (float)D; }
		if ((*Nav)->TryGetNumberField(TEXT("max_climb_cm"), D)) { Out.MaxClimbCM = (float)D; }
	}
	UE_LOG(LogCarlaAssetImport, Log, TEXT("Map manifest loaded: %s (track=%s)"),
		*Out.MapName, *Out.Track);
	return true;
}
