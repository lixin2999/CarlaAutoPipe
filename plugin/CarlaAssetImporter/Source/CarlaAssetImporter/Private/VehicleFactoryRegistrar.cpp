// Copyright CarlaAutoPipe Team. All Rights Reserved.
//
// 实现说明：FVehicleParameters 定义于 CARLA 0.9.16 源码 Carla 模块
// （CarlaServer/source/carla/Client/... 对应 UE 侧 CarlaWheeledVehicle.h /
// VehicleParameters.h）。为避免插件对工程模块的编译期依赖，全部字段通过
// 反射写入；Class 字段为 TSoftClassPtr<ACarlaWheeledVehicle>，按软路径写入。
#include "VehicleFactoryRegistrar.h"

#include "CarlaAssetImporter.h"
#include "Engine/Blueprint.h"
#include "Kismet2/KismetEditorUtilities.h"   // FKismetEditorUtilities
#include "UObject/UnrealType.h"
#include "UObject/Package.h"
#include "FileHelpers.h"

TArray<UCarlaVehicleFactoryRegistrar::FPendingRegistration>&
UCarlaVehicleFactoryRegistrar::GetQueue()
{
	// 进程级事务队列：Commandlet 生命周期内有效
	static TArray<FPendingRegistration> Queue;
	return Queue;
}

int32 UCarlaVehicleFactoryRegistrar::GetPendingCount()
{
	return GetQueue().Num();
}

void UCarlaVehicleFactoryRegistrar::ResetQueue()
{
	GetQueue().Reset();
}

bool UCarlaVehicleFactoryRegistrar::EnqueueRegistration(
	const FCarlaVehicleManifest& Manifest, UBlueprint* VehicleBP, bool bDryRun)
{
	if (!VehicleBP || !VehicleBP->GeneratedClass)
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("Registrar: invalid VehicleBP"));
		return false;
	}

	// 1. 加载 VehicleFactory 蓝图
	UBlueprint* FactoryBP = Cast<UBlueprint>(StaticLoadObject(
		UBlueprint::StaticClass(), nullptr,
		*Manifest.Registration.VehicleFactoryPath));
	if (!FactoryBP || !FactoryBP->GeneratedClass)
	{
		UE_LOG(LogCarlaAssetImport, Error,
			TEXT("Failed to load VehicleFactory at %s"),
			*Manifest.Registration.VehicleFactoryPath);
		return false;
	}

	// 2. 获取 CDO 并定位 Vehicles 数组属性
	UObject* CDO = FactoryBP->GeneratedClass->GetDefaultObject();
	FArrayProperty* VehiclesProp =
		CastField<FArrayProperty>(CDO->GetClass()->FindPropertyByName(TEXT("Vehicles")));
	if (!VehiclesProp)
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("Vehicles array property not found on CDO"));
		return false;
	}
	FScriptArrayHelper ArrayHelper(VehiclesProp,
		VehiclesProp->ContainerPtrToValuePtr<void>(CDO));

	// Struct 元素字段定位（FVehicleParameters：Make/Model/Class/Generation/...）
	UScriptStruct* ParamsStruct = nullptr;
	if (FStructProperty* Inner = CastField<FStructProperty>(VehiclesProp->Inner))
	{
		ParamsStruct = Inner->Struct;
	}
	if (!ParamsStruct)
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("Vehicles element is not a struct"));
		return false;
	}

	// 3. 幂等检查：相同 Make + Model 直接跳过（重复执行不产生重复条目）
	auto GetStrIn = [ParamsStruct](const uint8* Elem, const TCHAR* Name) -> FString
	{
		if (FStrProperty* P = CastField<FStrProperty>(ParamsStruct->FindPropertyByName(Name)))
		{
			return P->GetPropertyValue(P->ContainerPtrToValuePtr<void>(Elem));
		}
		return FString();
	};
	for (int32 i = 0; i < ArrayHelper.Num(); ++i)
	{
		const uint8* Elem = ArrayHelper.GetRawPtr(i);
		if (GetStrIn(Elem, TEXT("Make")) == Manifest.Make &&
			GetStrIn(Elem, TEXT("Model")) == Manifest.Model)
		{
			UE_LOG(LogCarlaAssetImport, Warning,
				TEXT("Vehicle %s.%s already registered — skip (idempotent)"),
				*Manifest.Make, *Manifest.Model);
			return true;
		}
	}

	if (bDryRun)
	{
		UE_LOG(LogCarlaAssetImport, Log,
			TEXT("[dry-run] would enqueue registration for %s.%s"),
			*Manifest.Make, *Manifest.Model);
		return true;
	}

	// 4. 数组新增元素并赋值（延迟编译：此处不触发 CompileBlueprint）
	const int32 NewIndex = ArrayHelper.AddZeroed();
	uint8* Elem = ArrayHelper.GetRawPtr(NewIndex);

	auto SetStr = [&](const TCHAR* Name, const FString& V)
	{
		if (FStrProperty* P = CastField<FStrProperty>(ParamsStruct->FindPropertyByName(Name)))
		{
			P->SetPropertyValue_InContainer(Elem, V);
		}
	};
	auto SetInt = [&](const TCHAR* Name, int32 V)
	{
		if (FIntProperty* P = CastField<FIntProperty>(ParamsStruct->FindPropertyByName(Name)))
		{
			P->SetPropertyValue_InContainer(Elem, V);
		}
	};

	SetStr(TEXT("Make"), Manifest.Make);     // 已强制小写（工程纪律）
	SetStr(TEXT("Model"), Manifest.Model);
	SetInt(TEXT("Generation"), Manifest.Generation);
	SetInt(TEXT("NumberOfWheels"), Manifest.Wheels);
	SetStr(TEXT("BaseType"), Manifest.BaseType);

	// Class 字段：TSoftClassPtr —— 以 BP_<Model>_C 软对象路径写入
	if (FProperty* ClassProp = ParamsStruct->FindPropertyByName(TEXT("Class")))
	{
		const FString ClassPath = VehicleBP->GeneratedClass->GetPathName(); // 形如 .../BP_Su7.BP_Su7_C
		if (FObjectPropertyBase* Obj = CastField<FObjectPropertyBase>(ClassProp))
		{
			// 硬引用 TSubclassOf：直接写入已加载类
			Obj->SetObjectPropertyValue(
				Obj->ContainerPtrToValuePtr<void>(Elem), VehicleBP->GeneratedClass);
		}
		else if (FStructProperty* SoftStruct = CastField<FStructProperty>(ClassProp);
			SoftStruct && SoftStruct->Struct->GetFName() == NAME_SoftObjectPtr)
		{
			// 软引用 TSoftClassPtr：构造 FSoftObjectPtr 写入
			using FSoftObjectPtrType = TSoftObjectPtr<UObject>;
			FSoftObjectPtrType* Soft =
				SoftStruct->ContainerPtrToValuePtr<FSoftObjectPtrType>(Elem);
			*Soft = FSoftObjectPtrType(FSoftObjectPath(ClassPath));
		}
	}

	// Colors：TArray<FLinearColor>
	if (FArrayProperty* ColorsProp =
		CastField<FArrayProperty>(ParamsStruct->FindPropertyByName(TEXT("Colors"))))
	{
		FScriptArrayHelper ColorsArray(ColorsProp,
			ColorsProp->ContainerPtrToValuePtr<void>(Elem));
		for (int32 c = 0; c < Manifest.Colors.Num(); ++c)
		{
			const int32 Idx = ColorsArray.AddZeroed();
			if (FStructProperty* LinearColor =
				CastField<FStructProperty>(ColorsProp->Inner))
			{
				*ColorsArray.GetPtr<FLinearColor>(Idx) = Manifest.Colors[c];
			}
		}
	}

	FPendingRegistration Pending;
	Pending.Manifest = Manifest;
	Pending.VehicleClassPath = VehicleBP->GeneratedClass->GetPathName();
	Pending.bNewEntry = true;
	GetQueue().Add(MoveTemp(Pending));

	UE_LOG(LogCarlaAssetImport, Log,
		TEXT("Enqueued (deferred compile) %s.%s -> queue depth %d"),
		*Manifest.Make, *Manifest.Model, GetQueue().Num());
	return true;
}

int32 UCarlaVehicleFactoryRegistrar::FlushPendingRegistrations(bool bDryRun)
{
	TArray<FPendingRegistration>& Queue = GetQueue();
	if (bDryRun || Queue.Num() == 0)
	{
		Queue.Reset();
		return 0;
	}

	int32 Failures = 0;
	// ★仅在所有车辆完成注入后统一编译一次（消除重复全图编译）
	const FCarlaVehicleManifest& First = Queue[0].Manifest;
	UBlueprint* FactoryBP = Cast<UBlueprint>(StaticLoadObject(
		UBlueprint::StaticClass(), nullptr, *First.Registration.VehicleFactoryPath));
	if (!FactoryBP)
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("Flush: VehicleFactory unloadable"));
		Failures = Queue.Num();
		Queue.Reset();
		return Failures;
	}

	if (!FKismetEditorUtilities::CompileBlueprint(FactoryBP))
	{
		// 只改 CDO 不编译会导致运行时失效 —— 编译失败直接报错
		UE_LOG(LogCarlaAssetImport, Error, TEXT("Flush: CompileBlueprint FAILED for VehicleFactory"));
		Failures = Queue.Num();
	}
	FactoryBP->MarkPackageDirty();

	// VehicleFactory 必须最后保存，确保所有依赖资产已先落盘
	TArray<UPackage*> Pkgs = { FactoryBP->GetPackage() };
	const bool bSaved = FEditorFileUtils::SavePackages(Pkgs, /*bPromptToSave=*/false);
	if (!bSaved)
	{
		UE_LOG(LogCarlaAssetImport, Error, TEXT("Flush: save VehicleFactory package failed"));
		Failures += 1;
	}
	UE_LOG(LogCarlaAssetImport, Log, TEXT("Flush: %d pending registrations compiled once, saved=%d"),
		Queue.Num(), bSaved ? 1 : 0);
	Queue.Reset();
	return Failures;
}
