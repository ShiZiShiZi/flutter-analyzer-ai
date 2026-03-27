---
name: license-check
description: "Identify license type and classify into four categories for a Flutter plugin"
metadata:
  category: "flutter-analysis"
---

## Goal
识别 Flutter 插件的 License 类型，归入四分类之一。

## Steps

### Step 1 — 读取 LICENSE 文件

```bash
ls LICENSE* 2>/dev/null
cat LICENSE 2>/dev/null || cat LICENSE.md 2>/dev/null || cat LICENSE.txt 2>/dev/null || echo "NO_LICENSE_FILE"
```

### Step 2 — 读取 pubspec.yaml license 字段

```bash
grep -E "^license:" pubspec.yaml 2>/dev/null || echo "NO_LICENSE_FIELD"
```

### Step 3 — 四分类归类

| category | 说明 | 典型协议 |
|----------|------|---------|
| `permissive` | 宽松友好 | MIT、Apache-2.0、BSD-2-Clause、BSD-3-Clause、ISC、Unlicense、CC0-1.0、Zlib、PSF |
| `copyleft` | 有传染性 | GPL-2.0、GPL-3.0、AGPL-3.0、LGPL-2.1、LGPL-3.0、MPL-2.0、EUPL-1.2 |
| `proprietary` | 专有许可 | LICENSE 含 `proprietary` / `all rights reserved` / `commercial` 等字样；闭源商业 SDK 用户协议；pubspec.yaml license 为厂商自定义协议名 |
| `undeclared` | 未声明 | 无 LICENSE 文件且 pubspec.yaml 无 license 字段；内容无法识别为任何已知协议 |

## Output

```json
{
  "declared_license": "MIT",
  "category": "permissive",
  "evidence": ["LICENSE:1 (MIT License)"]
}
```

字段说明：
- `declared_license`：识别出的协议名称，按以下优先级填写：
  1. 标准开源协议 → 使用 SPDX 标识符（`MIT`、`Apache-2.0`、`GPL-3.0`、`LGPL-2.1` 等）
  2. 商业/厂商协议 → 使用协议文件或 pubspec.yaml 中的实际协议名称（如 `腾讯微信SDK用户协议`、`支付宝SDK协议`）
  3. 无法识别的自定义协议 → 填 `"Proprietary"`
  4. 完全未声明 → 填 `null`
- `category`：`permissive` | `copyleft` | `proprietary` | `undeclared`
- `evidence`：支撑判断的文件路径或关键文本片段
