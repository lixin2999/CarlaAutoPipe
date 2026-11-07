// Copyright CarlaAutoPipe Team. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"

/**
 * ★黄金模板绝对哈希卡点（V1.4 §4.3）。
 *
 * 算法与 carla_asset/checksum.py 完全一致：
 *  1. 递归枚举目录文件，忽略 .DS_Store / Thumbs.db / desktop.ini；
 *  2. 每个文件计算 SHA-256 二进制摘要（32B）；
 *  3. 按 POSIX 相对路径字典序升序；
 *  4. 累积字节流 = Σ( UTF8(relpath) + 0x00 + 文件摘要(32B) )；
 *  5. 对累积字节流再做 SHA-256 → 64 位小写十六进制。
 *
 * 在 Commandlet 最前端（Manifest 校验之后、复制之前）执行；
 * 不匹配直接返回退出码 3（ENVIRONMENT_ERROR）。
 */
class FCarlaTemplateHashGuard
{
public:
	/** 计算目录指纹。目录不存在返回 false。 */
	static bool ComputeDirectoryDigest(const FString& DirPath, FString& OutHex64);

	/** 卡点校验：目录指纹与期望值比对（大小写不敏感）。 */
	static bool Verify(const FString& DirPath, const FString& ExpectedHex64, FString& OutActualHex64);

	/** 将 /Game 内容路径映射为磁盘目录。 */
	static FString GamePathToDisk(const FString& GamePath);
};

/**
 * 内嵌 SHA-256 流式实现（FIPS 180-4 标准算法的独立实现）。
 * UE4.26 Core 仅自带 SHA-1（FSHAHash），为避免依赖引擎私有/OpenSSL
 * 模块的版本差异，保证与 Python hashlib.sha256 逐字节一致，此实现自包含。
 */
class FCarlaSha256
{
public:
	FCarlaSha256();
	void Update(const uint8* Data, int64 Len);
	void Update(const FString& Utf8String);           // UTF-8 编码后累加
	void UpdateUint8(uint8 Byte);
	/** 完成计算并输出 32 字节摘要（对象此后不可复用）。 */
	void Final(uint8 OutDigest[32]);
	/** 完成计算并输出 64 位小写十六进制。 */
	FString FinalHex();

private:
	void ProcessBlock(const uint8 Block[64]);

	uint32 H[8];
	uint64 BitLen = 0;
	int64 BufLen = 0;
	uint8 Buffer[64];
};
