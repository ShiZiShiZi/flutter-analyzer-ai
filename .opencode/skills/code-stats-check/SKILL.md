---
name: code-stats-check
description: "Count source lines of code across Dart, FFI C, Android, and iOS layers in a Flutter plugin"
metadata:
  category: "flutter-analysis"
---

## Goal
统计 Flutter 插件各层源码规模，分四层：Dart、Dart 依赖的 C（FFI）、Android 原生、iOS 原生。

**路径约定**：以下所有命令均需在仓库根目录下执行，或显式指定仓库路径。

**排除规则**（所有层通用）：
- 测试代码：`test/` `integration_test/` `test_driver/` `src/test/` `src/androidTest/`
- 示例代码：`example/`
- 生成代码：`*.g.dart` `*.freezed.dart` `*.pb.dart` `*.pbenum.dart`
- 构建产物：`build/` `.dart_tool/` `Pods/` `.gradle/`

**有效行计算**（排除空行和纯注释行）：
```bash
find <path> <filters> | xargs cat 2>/dev/null | grep -cEv '^\s*(//|/\*|\*+/|\*|$)'
```

每个语言条目格式：`{"files": N, "lines": N, "effective_lines": N}`，无该语言源码则为 `null`。

---

## Step 1 — Dart 层

```bash
# 文件数
find lib/ -name "*.dart" ! -name "*.g.dart" ! -name "*.freezed.dart" \
  ! -name "*.pb.dart" ! -name "*.pbenum.dart" 2>/dev/null | wc -l

# 总行数
find lib/ -name "*.dart" ! -name "*.g.dart" ! -name "*.freezed.dart" \
  ! -name "*.pb.dart" ! -name "*.pbenum.dart" 2>/dev/null | xargs cat 2>/dev/null | wc -l

# 有效行数
find lib/ -name "*.dart" ! -name "*.g.dart" ! -name "*.freezed.dart" \
  ! -name "*.pb.dart" ! -name "*.pbenum.dart" 2>/dev/null \
  | xargs cat 2>/dev/null | grep -cEv '^\s*(//|/\*|\*+/|\*|$)'
```

---

## Step 2 — FFI C 层（Dart 依赖的 C/C++）

查找仓库中不属于 android/ 或 ios/ 的 C/C++ 源文件（FFI 绑定代码通常在 `src/` 或根目录）：

```bash
# 定位 FFI C 源文件
find . \( -name "*.c" -o -name "*.cpp" -o -name "*.cc" -o -name "*.h" \) \
  ! -path "*/android/*" ! -path "*/ios/*" ! -path "*/example/*" \
  ! -path "*/build/*" ! -path "*/.dart_tool/*" 2>/dev/null | head -20

# 文件数
find . \( -name "*.c" -o -name "*.cpp" -o -name "*.cc" -o -name "*.h" \) \
  ! -path "*/android/*" ! -path "*/ios/*" ! -path "*/example/*" \
  ! -path "*/build/*" ! -path "*/.dart_tool/*" 2>/dev/null | wc -l

# 总行数
find . \( -name "*.c" -o -name "*.cpp" -o -name "*.cc" -o -name "*.h" \) \
  ! -path "*/android/*" ! -path "*/ios/*" ! -path "*/example/*" \
  ! -path "*/build/*" ! -path "*/.dart_tool/*" 2>/dev/null | xargs cat 2>/dev/null | wc -l

# 有效行数
find . \( -name "*.c" -o -name "*.cpp" -o -name "*.cc" -o -name "*.h" \) \
  ! -path "*/android/*" ! -path "*/ios/*" ! -path "*/example/*" \
  ! -path "*/build/*" ! -path "*/.dart_tool/*" 2>/dev/null \
  | xargs cat 2>/dev/null | grep -cEv '^\s*(//|/\*|\*+/|\*|$)'
```

> 无 FFI C 源文件（`ffi_involved=false` 且目录不存在）→ `ffi_c: null`

---

## Step 3 — Android 原生层

分语言单独统计（搜索范围：`android/src/main/` + `android/cpp/`）：

**Java：**
```bash
find android/src/main android/cpp -name "*.java" 2>/dev/null | wc -l
find android/src/main android/cpp -name "*.java" 2>/dev/null | xargs cat 2>/dev/null | wc -l
find android/src/main android/cpp -name "*.java" 2>/dev/null | xargs cat 2>/dev/null | grep -cEv '^\s*(//|/\*|\*+/|\*|$)'
```

**Kotlin：**
```bash
find android/src/main android/cpp -name "*.kt" 2>/dev/null | wc -l
find android/src/main android/cpp -name "*.kt" 2>/dev/null | xargs cat 2>/dev/null | wc -l
find android/src/main android/cpp -name "*.kt" 2>/dev/null | xargs cat 2>/dev/null | grep -cEv '^\s*(//|/\*|\*+/|\*|$)'
```

**C/C++（含 .h）：**
```bash
find android/ \( -name "*.c" -o -name "*.cpp" -o -name "*.cc" -o -name "*.h" \) \
  ! -path "*/.gradle/*" ! -path "*/build/*" 2>/dev/null | wc -l
find android/ \( -name "*.c" -o -name "*.cpp" -o -name "*.cc" -o -name "*.h" \) \
  ! -path "*/.gradle/*" ! -path "*/build/*" 2>/dev/null | xargs cat 2>/dev/null | wc -l
find android/ \( -name "*.c" -o -name "*.cpp" -o -name "*.cc" -o -name "*.h" \) \
  ! -path "*/.gradle/*" ! -path "*/build/*" 2>/dev/null \
  | xargs cat 2>/dev/null | grep -cEv '^\s*(//|/\*|\*+/|\*|$)'
```

---

## Step 4 — iOS 原生层

分语言单独统计（排除 `Pods/` `example/` `build/`）：

**Swift：**
```bash
find ios/ -name "*.swift" ! -path "*/Pods/*" ! -path "*/example/*" ! -path "*/build/*" 2>/dev/null | wc -l
find ios/ -name "*.swift" ! -path "*/Pods/*" ! -path "*/example/*" ! -path "*/build/*" 2>/dev/null | xargs cat 2>/dev/null | wc -l
find ios/ -name "*.swift" ! -path "*/Pods/*" ! -path "*/example/*" ! -path "*/build/*" 2>/dev/null | xargs cat 2>/dev/null | grep -cEv '^\s*(//|/\*|\*+/|\*|$)'
```

**ObjC / ObjC++（.m / .mm）：**
```bash
find ios/ \( -name "*.m" -o -name "*.mm" \) ! -path "*/Pods/*" ! -path "*/example/*" ! -path "*/build/*" 2>/dev/null | wc -l
find ios/ \( -name "*.m" -o -name "*.mm" \) ! -path "*/Pods/*" ! -path "*/example/*" ! -path "*/build/*" 2>/dev/null | xargs cat 2>/dev/null | wc -l
find ios/ \( -name "*.m" -o -name "*.mm" \) ! -path "*/Pods/*" ! -path "*/example/*" ! -path "*/build/*" 2>/dev/null | xargs cat 2>/dev/null | grep -cEv '^\s*(//|/\*|\*+/|\*|$)'
```

**Headers（.h）：**
```bash
find ios/ -name "*.h" ! -path "*/Pods/*" ! -path "*/example/*" ! -path "*/build/*" 2>/dev/null | wc -l
find ios/ -name "*.h" ! -path "*/Pods/*" ! -path "*/example/*" ! -path "*/build/*" 2>/dev/null | xargs cat 2>/dev/null | wc -l
find ios/ -name "*.h" ! -path "*/Pods/*" ! -path "*/example/*" ! -path "*/build/*" 2>/dev/null | xargs cat 2>/dev/null | grep -cEv '^\s*(//|/\*|\*+/|\*|$)'
```

---

## Step 5 — 公开 API 面积（Dart 对外暴露接口数）

Dart 中 **无下划线前缀** 的顶层/成员声明即为 public。插件对外暴露的范围由 `lib/<name>.dart` 的 `export` 指令决定。

使用 Python3 做基础语法解析（先去除注释和字符串字面量，再按缩进+关键字计数），结果精确：

```bash
python3 << 'PYEOF'
import re, json
from pathlib import Path

lib_path = Path('lib')
if not lib_path.exists():
    print(json.dumps({"exported_files":0,"public_classes":0,"public_methods":0,"public_top_level_functions":0}))
    exit()

SKIP = ('.g.dart', '.freezed.dart', '.pb.dart', '.pbenum.dart')
KEYWORDS = {'if','else','for','while','switch','return','final','const','var','new',
            'true','false','null','super','this','throw','try','catch','assert','await','yield',
            'import','export','part','library','show','hide','as','in','is','on'}

def strip_comments_and_strings(text):
    text = re.sub(r"'''.*?'''", "''", text, flags=re.DOTALL)
    text = re.sub(r'""".*?"""', '""', text, flags=re.DOTALL)
    text = re.sub(r"r'[^']*'", "''", text)
    text = re.sub(r'r"[^"]*"', '""', text)
    text = re.sub(r"'[^'\\\n]*(?:\\.[^'\\\n]*)*'", "''", text)
    text = re.sub(r'"[^"\\\n]*(?:\\.[^"\\\n]*)*"', '""', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text

exported_files = 0
public_classes = 0
public_methods = 0
public_top_level_fns = 0

# exports from entry files (lib/*.dart only, not lib/src/)
for f in lib_path.glob('*.dart'):
    raw = f.read_text(errors='replace')
    exported_files += sum(1 for l in raw.splitlines() if l.strip().startswith('export '))

CLASS_PAT   = re.compile(r'^(?:abstract\s+)?class\s+([A-Z])|^mixin\s+([A-Z])|^enum\s+([A-Z])|^extension\s+([A-Z])')
METHOD_PAT  = re.compile(r'^(?:(?:static|abstract|async|external|factory|const|late|covariant)\s+)*(?:[\w<>\[\],?.]+\s+)*([a-z]\w*)\s*[(<]')
GETSET_PAT  = re.compile(r'^(?:static\s+)?(?:get|set)\s+([a-z]\w+)')
TOPLVL_PAT  = re.compile(r'^(?:Future|Stream|void|String|int|bool|double|num|List|Map|Set|dynamic|Iterable)\s+([a-z]\w*)\s*[(<]')

for dart_file in lib_path.rglob('*.dart'):
    if any(dart_file.name.endswith(s) for s in SKIP):
        continue
    text = strip_comments_and_strings(dart_file.read_text(errors='replace'))
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            if CLASS_PAT.match(s):
                public_classes += 1
            else:
                m = TOPLVL_PAT.match(s)
                if m and m.group(1) not in KEYWORDS:
                    public_top_level_fns += 1
        elif indent >= 2:
            m = GETSET_PAT.match(s)
            if m and not m.group(1).startswith('_'):
                public_methods += 1
                continue
            m = METHOD_PAT.match(s)
            if m and m.group(1) not in KEYWORDS and not m.group(1).startswith('_'):
                public_methods += 1

print(json.dumps({
    "exported_files": exported_files,
    "public_classes": public_classes,
    "public_methods": public_methods,
    "public_top_level_functions": public_top_level_fns,
    "total_public_api": public_methods + public_top_level_fns
}, indent=2))
PYEOF
```

**字段说明**：
- `exported_files`：主入口 `export` 指令数，代表对外开放的文件范围
- `public_classes`：公开 class / abstract class / mixin / enum / extension 总数
- `public_methods`：公开实例方法 + 静态方法 + getter/setter（排除 `_` 前缀私有成员）
- `public_top_level_functions`：不属于任何类的公开顶层函数数
- `total_public_api`：对外暴露的可调用 API 总数（`public_methods` + `public_top_level_functions`）

---

## Output

```json
{
  "dart": {"files": 12, "lines": 1840, "effective_lines": 1520},
  "ffi_c": {"files": 3, "lines": 210, "effective_lines": 175},
  "android": {
    "java": null,
    "kotlin": {"files": 3, "lines": 420, "effective_lines": 380},
    "c_cpp": {"files": 5, "lines": 380, "effective_lines": 310}
  },
  "ios": {
    "swift": null,
    "objc": {"files": 4, "lines": 610, "effective_lines": 540},
    "headers": {"files": 2, "lines": 80, "effective_lines": 60}
  },
  "public_api": {
    "exported_files": 3,
    "public_classes": 8,
    "public_methods": 42,
    "public_top_level_functions": 2,
    "total_public_api": 44
  }
}
```
