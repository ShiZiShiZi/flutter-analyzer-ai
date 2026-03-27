# Flutter Plugin Analyzer - 基于 opencode 原生特性的实现规划

## Context

构建一个系统，输入 Flutter 插件 Git 仓库地址，自动克隆源码，利用 **opencode 的 Skills + Agent 原生特性**驱动 AI 分析，输出结构化 JSON 报告，涵盖：
- 云服务依赖（Firebase/AWS/GCP 等）
- 付费功能（内购/订阅/收费 SDK）
- License 友好性（类型 + 商业限制）

---

## 核心设计思路

**不把 opencode 当黑盒 CLI 调用，而是构建一个原生 opencode 项目：**

```
Python 脚本（驱动层）
    ↓ git clone
    ↓ 注入 .opencode/ 配置
    ↓ opencode run --agent flutter-analyzer
opencode（分析层）
    ↓ 自动 skill_use 加载各维度技能
    ↓ 三个专项 Skill 分别分析
    ↓ 输出结构化 JSON
Python 脚本（收集层）
    ↓ 捕获 stdout
    ↓ 提取 JSON
    → 写入报告文件
```

---

## 项目结构

```
flutter_analysis/
├── pyproject.toml                         # uv 管理，无需第三方依赖
├── main.py                                # 入口：git clone + 注入配置 + 调用 opencode
├── src/
│   └── downloader.py                      # git clone 到临时目录
├── .opencode/
│   ├── agents/
│   │   └── flutter-analyzer.md            # 主分析 Agent（只读，低温度）
│   └── skills/
│       ├── cloud-service-check/
│       │   └── SKILL.md                   # 云服务依赖分析技能
│       ├── payment-check/
│       │   └── SKILL.md                   # 付费功能分析技能
│       └── license-check/
│           └── SKILL.md                   # License 分析技能
└── output/                                # JSON 报告输出目录
```

---

## 模型选择

| 模型 | Context | 推荐度 | 说明 |
|------|---------|--------|------|
| **qwen3-coder-plus** | 1M | ★★★★★ | 编码专项，1M 上下文，首选 |
| qwen3-coder-next | 262K | ★★★★ | 编码专项，上下文偏小 |
| qwen3.5-plus | 1M | ★★★ | 通用+思考模式，非编码专项 |

**推荐 `qwen3-coder-plus`**：1M 上下文可完整分析大型 Flutter 仓库，编码专项对 pubspec.yaml / import / SDK 调用理解更准确。

> model ID 需用 `opencode models` 确认完整的 `provider/model-id` 格式。

---

## 关键文件设计

### `.opencode/agents/flutter-analyzer.md`
```markdown
---
description: "Flutter plugin analyzer: cloud, payment, license"
mode: subagent
model: qwen3-coder-plus     # 确认 provider/model ID 后替换
temperature: 0.1            # Qwen 默认 0.55，降低保证分析确定性
tools:
  bash: true       # 允许 grep/find/cat 读取源码
  edit: false      # 禁止修改代码
  write: false     # 禁止写入文件
---
你是一个 Flutter 插件分析专家，只读分析，不修改任何代码。

依次执行以下三步：
1. 使用 cloud-service-check skill 分析云服务依赖
2. 使用 payment-check skill 分析付费功能
3. 使用 license-check skill 分析 License

最终输出一个完整的 JSON 对象（不要有额外文字）：
{
  "repo_url": "<仓库地址>",
  "cloud_services": { "uses_cloud": bool, "services": [], "evidence": [] },
  "payment": { "involves_payment": bool, "payment_type": [], "evidence": [] },
  "license": { "type": "MIT", "commercial_friendly": bool, "restrictions": [] }
}
```

### `.opencode/skills/cloud-service-check/SKILL.md`
```markdown
---
name: cloud-service-check
description: "Detect cloud service dependencies in Flutter plugin source code"
metadata:
  category: "flutter-analysis"
---
## Goal
分析 Flutter 插件是否依赖云端服务

## Use This Skill When
- 分析 Flutter 插件的云服务依赖

## Steps
1. 检查 pubspec.yaml 中的依赖项（firebase_*, aws_*, supabase* 等）
2. 搜索 import 语句（grep -r "firebase\|aws\|gcp\|supabase\|azure"）
3. 检查 SDK 初始化代码（FirebaseApp.initializeApp、Amplify.configure 等）
4. 检查网络请求目标域名（http.get、Dio 调用的 URL）

## Output
JSON 片段：{"uses_cloud": bool, "services": [...], "evidence": [...]}
```

### `.opencode/skills/payment-check/SKILL.md`
检查 revenue_cat、stripe、in_app_purchase、pay 等依赖和关键词，识别付费 SDK 接入、订阅逻辑、内购流程。

### `.opencode/skills/license-check/SKILL.md`
读取 LICENSE 文件、pubspec.yaml 的 license 字段，识别 SPDX 标识符，判断商业友好性（MIT/Apache-2.0 友好，GPL/AGPL 限制较多）。

---

## Python 驱动层（main.py）

```
流程：
1. argparse 解析 URL 参数
2. downloader.py: git clone <url> 到 tempfile.mkdtemp()
3. 将 .opencode/ 目录复制到克隆的仓库目录中
4. subprocess.run(
     ["opencode", "run", "--agent", "flutter-analyzer",
      f"分析这个 Flutter 插件，仓库地址：{url}"],
     cwd=<克隆目录>,
     capture_output=True
   )
5. 从 stdout 提取 JSON（regex 找 { ... }）
6. 写入 output/<repo_name>.json
7. 清理临时目录（除非 --keep）
```

---

## 关键文件清单

| 文件 | 核心职责 |
|------|---------|
| `main.py` | CLI 入口，驱动整体流程 |
| `src/downloader.py` | git clone + 临时目录管理 |
| `.opencode/agents/flutter-analyzer.md` | 只读分析 Agent，编排三个 Skill，强制 JSON 输出 |
| `.opencode/skills/cloud-service-check/SKILL.md` | 云服务依赖检测 Skill |
| `.opencode/skills/payment-check/SKILL.md` | 付费功能检测 Skill |
| `.opencode/skills/license-check/SKILL.md` | License 分析 Skill |
| `pyproject.toml` | 纯标准库，无第三方依赖 |

---

## 依赖

- Python 3.10+（标准库：subprocess、tempfile、json、re、shutil、argparse）
- 系统安装：`git`、`opencode`（已登录配置好模型）

**clone 方式**：使用 SSH（`git@github.com:xxx/xxx.git`），HTTPS 方式网络不通。

---

## 验证方法

```bash
# 环境检查
which git opencode

# 运行分析
python main.py https://github.com/FirebaseExtended/flutterfire

# 检查输出
cat output/flutterfire.json

# 带调试信息
python main.py <url> --verbose --keep
```

期望 JSON 输出包含三个维度的 `uses_cloud/involves_payment/license` 字段及证据列表。
