---
name: dependency-analysis
description: "Analyze Flutter plugin dependency structure including Dart, Android native, iOS native dependencies"
---

## Goal
对 Flutter 插件进行完整依赖结构分析，按依赖类型分类输出。

**严格按以下 5 步顺序执行，所有命令必须在给定仓库路径下运行。**

---

## 最终输出结构（7 个顶层字段）

1. `plugin_metadata`       — Step 1 产出
2. `dart_plugin_deps`      — Step 2 产出（Dart 包依赖，无需 source_availability）
3. `android_jar_aar_deps`  — Step 3 产出（build.gradle Maven + 本地 JAR/AAR）
4. `ios_pod_deps`          — Step 4 产出（.podspec CocoaPod 依赖）
5. `c_library_deps`        — Step 5 产出（FFI / Android NDK / iOS 链接的 C 库）
6. `so_deps`               — Step 5 产出（仓库内预编译 .so / .a 二进制文件）
7. `platform_api_deps`     — Step 5 产出（平台专有系统 API，如 OpenGL ES / UIKit）

---

## source_availability 判定规则（Step 3 / 4 / 5 共用）

对 `android_jar_aar_deps`、`ios_pod_deps`、`c_library_deps`、`so_deps` 中每个条目填写：
- `source_availability`：按下表判定
- `description`：一句话中文说明该库是什么（如"支付宝官方 Android SDK"、"OpenSSL 安全通信库"）

| 值 | 判断规则 |
|----|---------|
| `SOURCE_IN_REPO` | `source_type` 为 `LOCAL_FILE` / `LOCAL_PATH`，路径在仓库内；本地 .aar/.jar/.so/.a 可在仓库中找到 |
| `OPEN_SOURCE_COMMUNITY` | 知名开源库，可在公开平台找到源码。包括：`androidx.*`、OkHttp、Retrofit、Glide、Kotlin 标准库、Alamofire、SDWebImage；NDK 系统库（`libc`、`libm`、`libz`、`libssl`、`log`、`android`）；iOS 基础系统库 |
| `COMMERCIAL_PUBLIC` | 公开商业或生态厂商 SDK，有官方文档但源码不完全开放。包括：`com.google.android.gms.*`、`com.google.firebase.*`、`com.huawei.*`、支付宝、微信、极光推送等 |
| `PRIVATE_INTERNAL` | 私有 Maven 仓库 URL、私有 git Pod source、无法在公开平台查到的内部包名 |
| `UNKNOWN_BLACKBOX` | 本地 .aar / .jar / .so / .a 且无法匹配任何已知库，来源不明 |

> `androidx.*` → `OPEN_SOURCE_COMMUNITY`（不是 COMMERCIAL_PUBLIC）
> `com.google.android.gms:play-services-*` 和 `com.google.firebase:*` → `COMMERCIAL_PUBLIC`

---

## Step 1 — 插件元数据

```bash
cat pubspec.yaml
ls -la
ls -la android/ 2>/dev/null || echo "NO_ANDROID_DIR"
ls -la ios/ 2>/dev/null || echo "NO_IOS_DIR"
ls -la lib/ 2>/dev/null | head -20
```

**架构类型检测逻辑（按顺序判断，第一个匹配即停止）：**

| 条件 | 结论 |
|---|---|
| pubspec `name` 以 `_platform_interface` 结尾 | `federated_platform_interface` |
| `dependencies` 含 `*_platform_interface` 且自身有单平台 native 目录 | `federated_platform_impl` |
| `dependencies` 含 `*_platform_interface` 且无 native 目录 | `federated_app_facing` |
| 有 `flutter.plugin.platforms` 或存在 android/ 或 ios/ 目录 | `monolithic_plugin` |
| 其余 | `dart_only` |

**platform_support**：从 `flutter.plugin.platforms` 枚举，无该字段则根据目录推断。

**ffi_involved**：检查 pubspec `dependencies` 中是否有 `ffi`，以及是否有 `.dart` 文件含 `dart:ffi` import。

**repository_url**：取 pubspec.yaml `repository`；无则取 `homepage`（仅限 github.com / gitlab.com / bitbucket.org / gitee.com / codeberg.org / gitcode.com）；均无则 `null`。

**federation_group**：仅联合插件填写；非联合插件置 `null`。

| architecture | federation_group 取值 |
|---|---|
| `federated_platform_interface` | pubspec `name` 去掉 `_platform_interface` 后缀 |
| `federated_app_facing` | pubspec `name` 本身 |
| `federated_platform_impl` | dependencies 中 `*_platform_interface` 包名去掉后缀 |
| `monolithic_plugin` / `dart_only` | `null` |

**environment**：从 `environment:` 块提取 dart_sdk 和 flutter_sdk 约束，各含 `raw`、`min`、`min_op`、`max`、`max_op`（`^X.Y.Z` 展开为下一主版本 + `<`）。

---

## Step 2 — Dart 包依赖

```bash
cat pubspec.yaml
cat pubspec.lock 2>/dev/null || echo "NO_LOCK_FILE"
```

从 `pubspec.yaml` 提取：
- `direct`：`dependencies:` 下所有包（排除 `flutter` / `flutter_localizations` / `dart:*`），每条含 `name`、`version_constraint`、`resolved_version`（来自 lock）、`evidence`
- `dev`：`dev_dependencies:` 下所有包，每条含 `name`、`version_constraint`、`evidence`
- `overrides`：`dependency_overrides:` 块（若有）
- `transitive_count`：pubspec.lock 总条目数减去 direct+dev 数量（无 lock 则 -1）

---

## Step 3 — Android JAR/AAR 依赖

```bash
find android/ -name "build.gradle" -o -name "build.gradle.kts" 2>/dev/null | head -5
cat android/build.gradle 2>/dev/null || cat android/build.gradle.kts 2>/dev/null || echo "NO_ANDROID_BUILD"
find android/ -name "*.aar" -o -name "*.jar" 2>/dev/null | grep -v ".dart_tool" | head -20
```

从 `build.gradle` 提取所有 `implementation`/`api`/`compileOnly`/`runtimeOnly` 依赖条目，每条字段：
- `name`：
  - REMOTE 类型：`group:artifact`（如 `com.google.android.gms:play-services-base`）
  - LOCAL_FILE 类型：库名（不含版本号和后缀，如 `afservicesdk`）
- `version`：版本号（含变量名如 `$sdkVersion`）
- `filename`：**仅 LOCAL_FILE 类型填写**，完整文件名含后缀（如 `afservicesdk-1.0.0.220112162010.aar`），从 `find` 结果匹配；REMOTE 类型此字段为 `null`
- `dep_type`：`implementation | api | compileOnly | runtimeOnly | testImplementation`
- `source_type`：`REMOTE`（Maven 坐标）/ `LOCAL_FILE`（fileTree / 本地 .aar/.jar）
- `source_availability`：按共用规则判定
- `description`：一句话中文说明
- `evidence`：`android/build.gradle:<行号>`

同时记录：
- `has_java_kotlin`：android/ 下存在 .java 或 .kt 文件则为 `true`
- `has_ndk_cpp`：android/ 下存在 .c / .cpp / CMakeLists.txt / Android.mk 则为 `true`

---

## Step 4 — iOS Pod 依赖

```bash
find ios/ -name "*.podspec" 2>/dev/null | head -3
cat ios/*.podspec 2>/dev/null || echo "NO_PODSPEC"
```

从 `.podspec` 提取所有 `s.dependency` 条目，每条字段：
- `name`：Pod 名称
- `version`：版本约束（如 `~> 15.7.9`）
- `dep_type`：`dependency` / `test_spec_dependency`
- `source_type`：`REMOTE`（标准 CocoaPods）/ `LOCAL_PATH`（`:path =>`）/ `GIT_SOURCE`（`:git =>`）
- `source_availability`：按共用规则判定
- `description`：一句话中文说明
- `evidence`：`ios/<name>.podspec:<行号>`

同时记录：
- `has_native_code`：ios/ 下存在 .h / .m / .swift / .mm 文件则为 `true`

---

## Step 5 — C 库 / SO / 平台 API 分析

```bash
# FFI 扫描
grep -rn "dart:ffi\|DynamicLibrary\|Pointer<\|NativeFunction" --include="*.dart" . 2>/dev/null | head -30
grep -rn "DynamicLibrary\.open\|DynamicLibrary\.process" --include="*.dart" . 2>/dev/null | head -20

# Android NDK
find android/ -name "CMakeLists.txt" -o -name "Android.mk" 2>/dev/null | head -5
cat android/CMakeLists.txt android/src/main/cpp/CMakeLists.txt 2>/dev/null | head -60
find android/ -name "*.so" 2>/dev/null | grep -v ".dart_tool" | head -20

# iOS 原生
find ios/ -name "*.podspec" 2>/dev/null | xargs grep -h "frameworks\|libraries\|vendored" 2>/dev/null
find ios/ -name "*.a" -o -name "*.framework" 2>/dev/null | grep -v "Pods/" | head -20
find ios/ -name "*.h" -o -name "*.m" -o -name "*.mm" 2>/dev/null | grep -v "Pods/" | head -10
```

将结果分类到以下三个输出字段：

### c_library_deps — C 库依赖

收集所有以 C 接口形式链接的库（不含平台专有 API）：
- **FFI 来源**：`DynamicLibrary.open('libXxx.so')` 中引用的系统库（如 `libssl.so`、`libz.so`）
- **Android NDK 来源**：CMakeLists.txt `target_link_libraries` 中属于通用系统库的条目（`log`、`android`、`z`、`m`、`c`、`dl`、`pthread`、`atomic`、`stdc++`）
- **iOS 来源**：`s.libraries` 中指定的 C 库（如 `z`、`sqlite3`、`c++`）

每条字段：`name`、`platform`（`android` / `ios` / `cross_platform`）、`source_availability`、`description`、`evidence`

### so_deps — 预编译二进制

仓库内所有预编译的 .so / .a 文件（不含通过 Maven/CocoaPods 远程拉取的）：
- Android：`android/` 下的 .so 文件（jniLibs/ 或 libs/ 目录）
- iOS：`ios/` 下的 .a 文件和本地 .framework（排除 Pods/）
- FFI：`DynamicLibrary.open` 引用的本地文件路径

每条字段：`path`、`platform`（`android` / `ios` / `cross_platform`）、`source_availability`、`description`、`evidence`

### platform_api_deps — 平台专有系统 API

平台独有、在其他平台需要寻找替代方案的系统 API：

**Android 来源**（CMakeLists.txt `target_link_libraries` 中的平台 API）：

| 库名 | API 含义 |
|------|---------|
| `GLESv1_CM`、`GLESv2`、`GLESv3` | OpenGL ES 图形 API |
| `EGL` | EGL 图形上下文 |
| `vulkan` | Vulkan 图形/计算 API |
| `mediandk` | Android Media NDK（视频编解码） |
| `OpenSLES` | OpenSL ES 音频 API |
| `camera2ndk` | Camera2 NDK |
| `jnigraphics` | Bitmap 像素访问 API |
| `nativewindow` | ANativeWindow 图形窗口 |

**iOS 来源**（`.podspec` 的 `s.frameworks` / `s.weak_frameworks`）：

| Framework | API 含义 |
|-----------|---------|
| `UIKit` | iOS UI 框架 |
| `CoreMotion` | 运动传感器 |
| `AVFoundation` | 音视频 |
| `CoreBluetooth` | 蓝牙 |
| `ARKit` | 增强现实 |
| `CoreML` | 机器学习 |
| `Metal` | GPU 编程 |
| `CoreLocation` | 位置服务 |
| `MapKit` | 地图 |
| `StoreKit` | App 内购 |
| `AuthenticationServices` | Sign in with Apple |
| `LocalAuthentication` | 生物认证 |
| `WebKit` | Web 渲染 |
| `CallKit` | 通话 UI |
| `PushKit` | VoIP 推送 |
| `UserNotifications` | 通知 |
| `SafariServices` | Safari 集成 |
| 其他非 Foundation/CoreFoundation 的 Framework | 平台专有 API |

> `Foundation`、`CoreFoundation` 属于基础系统库，归入 `c_library_deps`，不放此处。

每条字段：`name`、`platform`（`android` / `ios`）、`description`、`evidence`

---

## Output

```json
{
  "plugin_metadata": {
    "architecture": "monolithic_plugin",
    "platform_support": ["android", "ios"],
    "ffi_involved": false,
    "repository_url": null,
    "federation_group": null,
    "environment": {
      "dart_sdk": {"raw": ">=2.13.0 <3.0.0", "min": "2.13.0", "min_op": ">=", "max": "3.0.0", "max_op": "<"},
      "flutter_sdk": {"raw": ">=2.2.0", "min": "2.2.0", "min_op": ">=", "max": null, "max_op": null}
    }
  },
  "dart_plugin_deps": {
    "direct": [
      {"name": "plugin_platform_interface", "version_constraint": "^2.1.8", "resolved_version": "2.1.8", "evidence": "pubspec.yaml:15"}
    ],
    "dev": [
      {"name": "flutter_test", "version_constraint": "sdk: flutter", "evidence": "pubspec.yaml:20"}
    ],
    "overrides": [],
    "transitive_count": 8
  },
  "android_jar_aar_deps": {
    "has_java_kotlin": true,
    "has_ndk_cpp": false,
    "deps": [
      {
        "name": "com.alipay.sdk:alipaysdk-android",
        "version": "15.8.14",
        "dep_type": "implementation",
        "source_type": "REMOTE",
        "source_availability": "COMMERCIAL_PUBLIC",
        "description": "支付宝官方 Android SDK",
        "evidence": "android/build.gradle:28"
      }
    ]
  },
  "ios_pod_deps": {
    "has_native_code": true,
    "deps": [
      {
        "name": "AlipaySDK-iOS",
        "version": "~> 15.7.9",
        "dep_type": "dependency",
        "source_type": "REMOTE",
        "source_availability": "COMMERCIAL_PUBLIC",
        "description": "支付宝官方 iOS SDK",
        "evidence": "ios/alipay_kit.podspec:18"
      }
    ]
  },
  "c_library_deps": [
    {
      "name": "libssl.so",
      "platform": "cross_platform",
      "source_availability": "OPEN_SOURCE_COMMUNITY",
      "description": "OpenSSL 安全通信库（FFI 调用）",
      "evidence": ["lib/src/ssl_ffi.dart:5 (DynamicLibrary.open('libssl.so'))"]
    },
    {
      "name": "log",
      "platform": "android",
      "source_availability": "OPEN_SOURCE_COMMUNITY",
      "description": "Android NDK 日志系统库",
      "evidence": ["android/CMakeLists.txt:12 (target_link_libraries ... log)"]
    }
  ],
  "so_deps": [
    {
      "path": "android/src/main/jniLibs/arm64-v8a/libfoo.so",
      "platform": "android",
      "source_availability": "UNKNOWN_BLACKBOX",
      "description": "来源不明的预编译 ARM64 动态库",
      "evidence": ["android/src/main/jniLibs/arm64-v8a/libfoo.so"]
    }
  ],
  "platform_api_deps": [
    {
      "name": "OpenGL ES (GLESv2)",
      "platform": "android",
      "description": "Android 图形渲染 API",
      "evidence": ["android/CMakeLists.txt:15 (target_link_libraries ... GLESv2)"]
    },
    {
      "name": "CoreMotion",
      "platform": "ios",
      "description": "iOS 运动传感器框架",
      "evidence": ["ios/alipay_kit.podspec:20 (s.frameworks 'CoreMotion')"]
    }
  ]
}
```
