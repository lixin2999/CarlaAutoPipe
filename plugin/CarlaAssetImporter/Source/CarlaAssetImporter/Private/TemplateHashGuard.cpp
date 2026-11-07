// Copyright CarlaAutoPipe Team. All Rights Reserved.
#include "TemplateHashGuard.h"

#include "CarlaAssetImporter.h"
#include "HAL/PlatformFilemanager.h"
#include "Misc/Paths.h"

// ===========================================================================
// FCarlaSha256 — FIPS 180-4 SHA-256 独立实现（与 Python hashlib.sha256 对齐）
// ===========================================================================
namespace
{
	const uint32 K256[64] = {
		0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
		0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
		0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
		0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
		0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
		0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
		0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
		0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
	};

	FORCEINLINE uint32 Ror32(uint32 X, int32 N) { return (X >> N) | (X << (32 - N)); }
}

FCarlaSha256::FCarlaSha256()
{
	// FIPS 180-4 初始哈希值（前 32 位平方根小数部分）
	H[0] = 0x6a09e667; H[1] = 0xbb67ae85; H[2] = 0x3c6ef372; H[3] = 0xa54ff53a;
	H[4] = 0x510e527f; H[5] = 0x9b05688c; H[6] = 0x1f83d9ab; H[7] = 0x5be0cd19;
}

void FCarlaSha256::ProcessBlock(const uint8 Block[64])
{
	uint32 W[64];
	for (int32 i = 0; i < 16; ++i)
	{
		W[i] = (uint32(Block[i * 4]) << 24) | (uint32(Block[i * 4 + 1]) << 16)
			 | (uint32(Block[i * 4 + 2]) << 8) | uint32(Block[i * 4 + 3]);
	}
	for (int32 i = 16; i < 64; ++i)
	{
		const uint32 S0 = Ror32(W[i - 15], 7) ^ Ror32(W[i - 15], 18) ^ (W[i - 15] >> 3);
		const uint32 S1 = Ror32(W[i - 2], 17) ^ Ror32(W[i - 2], 19) ^ (W[i - 2] >> 10);
		W[i] = W[i - 16] + S0 + W[i - 7] + S1;
	}

	uint32 a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
	for (int32 i = 0; i < 64; ++i)
	{
		const uint32 S1 = Ror32(e, 6) ^ Ror32(e, 11) ^ Ror32(e, 25);
		const uint32 Ch = (e & f) ^ (~e & g);
		const uint32 T1 = h + S1 + Ch + K256[i] + W[i];
		const uint32 S0 = Ror32(a, 2) ^ Ror32(a, 13) ^ Ror32(a, 22);
		const uint32 Maj = (a & b) ^ (a & c) ^ (b & c);
		const uint32 T2 = S0 + Maj;
		h = g; g = f; f = e; e = d + T1;
		d = c; c = b; b = a; a = T1 + T2;
	}
	H[0] += a; H[1] += b; H[2] += c; H[3] += d;
	H[4] += e; H[5] += f; H[6] += g; H[7] += h;
}

void FCarlaSha256::Update(const uint8* Data, int64 Len)
{
	BitLen += uint64(Len) * 8;
	while (Len > 0)
	{
		const int64 Take = FMath::Min<int64>(64 - BufLen, Len);
		FMemory::Memcpy(Buffer + BufLen, Data, Take);
		BufLen += Take;
		Data += Take;
		Len -= Take;
		if (BufLen == 64)
		{
			ProcessBlock(Buffer);
			BufLen = 0;
		}
	}
}

void FCarlaSha256::Update(const FString& Utf8String)
{
	FTCHARToUTF8 Utf8(*Utf8String);
	Update(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length());
}

void FCarlaSha256::UpdateUint8(uint8 Byte)
{
	Update(&Byte, 1);
}

void FCarlaSha256::Final(uint8 OutDigest[32])
{
	// 标准填充：0x80 + 零填充 + 64 位大端总位长（长度以填充前的原始数据为准）
	const uint64 OrigBitLen = BitLen;
	const uint8 Pad = 0x80;
	Update(&Pad, 1);
	const uint8 Zero = 0x00;
	while (BufLen != 56)
	{
		Update(&Zero, 1);
	}
	uint8 LenBE[8];
	for (int32 i = 0; i < 8; ++i)
	{
		LenBE[i] = uint8((OrigBitLen >> (56 - i * 8)) & 0xFF);
	}
	Update(LenBE, 8);

	for (int32 i = 0; i < 8; ++i)
	{
		OutDigest[i * 4]     = uint8(H[i] >> 24);
		OutDigest[i * 4 + 1] = uint8(H[i] >> 16);
		OutDigest[i * 4 + 2] = uint8(H[i] >> 8);
		OutDigest[i * 4 + 3] = uint8(H[i]);
	}
}

FString FCarlaSha256::FinalHex()
{
	uint8 Digest[32];
	Final(Digest);
	FString Out;
	for (uint8 B : Digest)
	{
		Out += FString::Printf(TEXT("%02x"), B);
	}
	return Out;
}

// ===========================================================================
// FCarlaTemplateHashGuard
// ===========================================================================
namespace
{
	bool IsIgnoredFile(const FString& FileName)
	{
		static const TCHAR* Ignored[] = { TEXT(".ds_store"), TEXT("thumbs.db"), TEXT("desktop.ini") };
		const FString Lower = FileName.ToLower();
		for (const TCHAR* Ig : Ignored)
		{
			if (Lower == Ig) { return true; }
		}
		return false;
	}

	bool FileSha256(const FString& AbsPath, FCarlaSha256& Inout)
	{
		// 分块流式读取，避免大文件整体载入
		TUniquePtr<IFileHandle> Handle(FPlatformFileManager::Get().GetPlatformFile().OpenRead(*AbsPath));
		if (!Handle)
		{
			return false;
		}
		constexpr int64 ChunkSize = 1024 * 1024;
		TArray<uint8> Chunk;
		Chunk.SetNumUninitialized(ChunkSize);
		int64 ReadTotal = 0;
		int32 Read = 0;
		do
		{
			Read = Handle->Read(Chunk.GetData(), ChunkSize);
			if (Read > 0)
			{
				// 单文件摘要独立计算：先算文件摘要再并入目录累加器
				Inout.Update(Chunk.GetData(), Read);
				ReadTotal += Read;
			}
		} while (Read > 0);
		return true;
	}
}

FString FCarlaTemplateHashGuard::GamePathToDisk(const FString& GamePath)
{
	// /Game/Carla/... -> <Project>/Content/Carla/...
	FString Rel = GamePath;
	FPaths::NormalizeFilename(Rel);
	if (Rel.StartsWith(TEXT("/Game/")))
	{
		Rel = Rel.RightChop(6);
	}
	return FPaths::ConvertRelativePathToFull(FPaths::ProjectContentDir() / Rel);
}

bool FCarlaTemplateHashGuard::ComputeDirectoryDigest(const FString& DirPath, FString& OutHex64)
{
	IPlatformFile& PlatformFile = FPlatformFileManager::Get().GetPlatformFile();
	if (!PlatformFile.DirectoryExists(*DirPath))
	{
		return false;
	}

	TArray<FString> Files;
	const FString Root = FPaths::ConvertRelativePathToFull(DirPath);
	IFileManager::Get().FindFilesRecursive(Files, *Root, TEXT("*"), true, false);

	// 相对路径（POSIX 正斜杠）+ 字典序排序，与 Python pathlib.as_posix() 一致
	TArray<FString> RelPaths;
	TMap<FString, FString> AbsByRel;
	for (const FString& Abs : Files)
	{
		const FString Name = FPaths::GetCleanFilename(Abs);
		if (IsIgnoredFile(Name))
		{
			continue;
		}
		FString Rel = Abs;
		FPaths::MakePathRelativeTo(Rel, *(Root / TEXT("")));
		FPaths::NormalizeFilename(Rel);          // 反斜杠 -> 正斜杠
		RelPaths.Add(Rel);
		AbsByRel.Add(Rel, Abs);
	}
	// ★大小写敏感码点序（与 Python entries.sort(key=e[0]) 严格对齐）：
	// FString::Sort 默认operator<走 ESearchCase::IgnoreCase，若目录内文件名存在
	// 大小写混合（如 Zebra.uasset vs apple.uasset）会导致两侧字节流顺序不一致，
	// 卡点误报退出码 3。
	RelPaths.Sort([](const FString& A, const FString& B)
	{
		return A.Compare(B, ESearchCase::CaseSensitive) < 0;
	});

	FCarlaSha256 Acc;
	for (const FString& Rel : RelPaths)
	{
		// 1) 计算文件级 SHA-256
		FCarlaSha256 FileHasher;
		if (!FileSha256(AbsByRel[Rel], FileHasher))
		{
			UE_LOG(LogCarlaAssetImport, Error, TEXT("Template file unreadable: %s"), *AbsByRel[Rel]);
			return false;
		}
		uint8 FileDigest[32];
		FileHasher.Final(FileDigest);

		// 2) 累加：UTF8(relpath) + 0x00 + 摘要
		Acc.Update(Rel);
		Acc.UpdateUint8(0x00);
		Acc.Update(FileDigest, 32);
	}
	OutHex64 = Acc.FinalHex();
	return true;
}

bool FCarlaTemplateHashGuard::Verify(const FString& DirPath, const FString& ExpectedHex64,
	FString& OutActualHex64)
{
	if (!ComputeDirectoryDigest(DirPath, OutActualHex64))
	{
		return false;
	}
	const bool bMatch = OutActualHex64.Equals(ExpectedHex64, ESearchCase::IgnoreCase);
	if (!bMatch)
	{
		UE_LOG(LogCarlaAssetImport, Error,
			TEXT("GOLDEN TEMPLATE HASH MISMATCH — expected=%s actual=%s dir=%s"),
			*ExpectedHex64, *OutActualHex64, *DirPath);
	}
	return bMatch;
}
