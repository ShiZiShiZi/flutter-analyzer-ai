---
name: cloud-service-check
description: "Detect cloud service topology (pure_edge / centralized / decentralized) in a Flutter plugin codebase"
metadata:
  category: "flutter-analysis"
---

## Goal
分析 Flutter 插件的端云拓扑类型，输出三分类标签：纯端（pure_edge）、端云协同中心化（centralized）、端云协同去中心化（decentralized）。
同时列出所有涉及的云端服务及其提供方。

## 端云拓扑定义

| 标签 | key | 核心判断标准 |
|------|-----|------------|
| 纯端 | `pure_edge` | 插件自身不发起任何外部网络请求；断网后核心功能 100% 正常 |
| 端云协同中心化 | `centralized` | 插件硬绑定到特定商业平台，需注册/AppKey，厂商云不可替换 |
| 端云协同去中心化 | `decentralized` | 插件会发起网络请求，但目标端点由开发者配置 / 可自托管 / P2P / 开放协议 |

**重要边界**：
- 如果插件**本身只提供**网络工具（不调用任何外部端点）→ `pure_edge`（如 http、dio、retrofit 包本身）
- 如果插件**自身代码**使用网络工具调用**可配置 URL / 无特定厂商**的外部端点 → `decentralized`
- 如果插件调用**特定厂商**的固定端点（需注册/AppKey）→ `centralized`
- `pure_edge` vs `decentralized` 的本质边界：**插件自身是否发起外部调用**，而非是否依赖特定厂商
- 优先级：`centralized` > `decentralized` > `pure_edge`

---

## 云端服务提供方字典

命中以下关键词时，按字典填写 `provider`（中文）和 `provider_en`（英文）：

| 关键词 | service 名称 | provider | provider_en |
|--------|-------------|----------|-------------|
| `firebase` | Firebase | Google | Google |
| `google_maps` / `google_maps_flutter` | Google Maps | Google | Google |
| `google_sign_in` | Google 登录 | Google | Google |
| `google_mobile_ads` / `admob` | AdMob | Google | Google |
| `jpush` / `jiguang` | 极光推送 | 极光 | Aurora Push |
| `getui` | 个推 | 个推 | Getui |
| `umeng` | 友盟+ | 友盟 | Umeng |
| `aliyun` / `aliyun_oss` / `aliyun_push` | 阿里云 | 阿里云 | Alibaba Cloud |
| `qiniu` | 七牛云 | 七牛 | Qiniu Cloud |
| `upyun` | 又拍云 | 又拍云 | Upyun |
| `tencent_cos` / `tencent_cloud` | 腾讯云 | 腾讯云 | Tencent Cloud |
| `tencent.*im` / `tim_` | 腾讯云 IM | 腾讯云 | Tencent Cloud |
| `trtc` / `tencent.*rtc` | 腾讯实时音视频 | 腾讯云 | Tencent Cloud |
| `tencent_map` | 腾讯地图 | 腾讯 | Tencent |
| `wechat` / `wxpay` / `wechat_kit` | 微信 SDK | 腾讯 | Tencent |
| `amap` / `gaode` | 高德地图 | 高德（阿里） | Amap/Alibaba |
| `baidu_map` / `baidu_aip` / `baidu` | 百度服务 | 百度 | Baidu |
| `rongcloud` | 融云 | 融云 | RongCloud |
| `netease.*im` / `nim_` / `netease_corekit` | 网易云信 | 网易 | NetEase Yunxin |
| `huawei` / `agconnect` / `hms` | 华为 HMS | 华为 | Huawei |
| `xiaomi.*push` / `mipush` | 小米推送 | 小米 | Xiaomi |
| `oppo.*push` / `heytap` | OPPO 推送 | OPPO | OPPO |
| `vivo.*push` | vivo 推送 | vivo | vivo |
| `agora` | 声网 | 声网 | Agora |
| `zego` | 即构科技 | 即构 | ZEGO |
| `alipay` | 支付宝 | 蚂蚁集团 | Ant Group |
| `stripe` | Stripe | Stripe | Stripe |
| `razorpay` | Razorpay | Razorpay | Razorpay |
| `adjust` | Adjust | Adjust | Adjust |
| `appsflyer` | AppsFlyer | AppsFlyer | AppsFlyer |
| `sensors_data` / `sa_flutter` | 神策数据 | 神策 | Sensors Data |
| `mixpanel` | Mixpanel | Mixpanel | Mixpanel |
| `supabase` | Supabase | Supabase | Supabase |
| `amplify` | AWS Amplify | Amazon | Amazon AWS |
| `iflytek` / `xunfei` | 讯飞 | 科大讯飞 | iFlytek |
| `tongyi` / `dashscope` | 通义千问 | 阿里云 | Alibaba Cloud |
| `wenxin` / `ernie` | 文心一言 | 百度 | Baidu |
| `zhipu` / `chatglm` | 智谱 AI | 智谱 | Zhipu AI |
| `minimax` | MiniMax | MiniMax | MiniMax |
| `deepseek` | DeepSeek | DeepSeek | DeepSeek |
| `moonshot` / `kimi` | Kimi | 月之暗面 | Moonshot AI |
| `baichuan` | 百川 AI | 百川智能 | Baichuan AI |
| `mapbox` | Mapbox | Mapbox | Mapbox |
| `here_sdk` | HERE Maps | HERE | HERE Technologies |
| `infura` | Infura RPC | Infura | ConsenSys/Infura |
| `alchemy` | Alchemy RPC | Alchemy | Alchemy |
| `twilio` | Twilio | Twilio | Twilio |
| `datadog` | Datadog | Datadog | Datadog |
| `sentry` | Sentry | Sentry | Sentry |
| `onesignal` | OneSignal | OneSignal | OneSignal |
| `braze` | Braze | Braze | Braze |

---

## Steps

### Step 1a — 中心化厂商信号检测

读取 `pubspec.yaml` 的 dependencies，并在代码中搜索特定厂商关键词：

```bash
# AppKey / 初始化信号（不含 configure，避免误报）
grep -r "AppKey\|appKey\|app_key\|AppSecret\|apiKey\|api_key\|SecretKey\|secretKey\|initializeApp" \
  --include="*.dart" -l
grep -r "AppKey\|appKey\|app_key\|AppSecret\|apiKey\|api_key\|SecretKey\|secretKey" \
  --include="*.yaml" -l

# 推送 / IM / 音视频 厂商
grep -r "firebase\|jpush\|jiguang\|getui\|umeng\|onesignal\|braze\
\|aliyun.*push\|huawei.*push\|xiaomi.*push\|oppo.*push\|vivo.*push\
\|rongcloud\|tencent.*im\|tim_flutter\|netease.*im\|nim_flutter\|netease_corekit\
\|agora\|zego\|trtc\|rtc_engine" \
  --include="*.yaml" --include="*.dart" -l -i

# 分析 / 监控 / 归因
grep -r "firebase_analytics\|umeng\|adjust\|appsflyer\|sensors_data\|sa_flutter\
\|mixpanel\|braze\|firebase_crashlytics\|datadog\|sentry" \
  --include="*.yaml" --include="*.dart" -l -i

# 地图服务（均需注册 API Key）
grep -r "google_maps_flutter\|amap_flutter\|gaode\|baidu.*map\|tencent_map\|mapbox\|here_sdk" \
  --include="*.yaml" --include="*.dart" -l -i

# 云存储 / 云平台
grep -r "aliyun_oss\|qiniu\|upyun\|tencent_cos\|supabase\|amplify\|appwrite\|back4app\
\|firebase_storage\|firebase_database\|firebase_firestore" \
  --include="*.yaml" --include="*.dart" -l -i

# 支付
grep -r "alipay\|wechat.*pay\|wxpay\|wechat_kit\|stripe\|razorpay\|paytm\|braintree" \
  --include="*.yaml" --include="*.dart" -l -i

# AI 云服务
grep -r "iflytek\|xunfei\|wenxin\|ernie\|tongyi\|dashscope\|zhipu\|chatglm\|baidu_aip\
\|minimax\|deepseek\|moonshot\|kimi\|baichuan\|openai\|twilio\|aliyun.*sms\|tencent.*sms\
\|infura\|alchemy" \
  --include="*.yaml" --include="*.dart" -l -i
```

**若命中** → 记录 centralized 信号，对照提供方字典填写 services，**继续执行 Step 1b/1c/Step 2**（不跳过，确保收集完整证据）。

---

### Step 1b — 端点配置信号检测

检测插件源码中是否存在可配置的 URL / 服务器地址参数：

```bash
grep -r "baseUrl\|base_url\|serverUrl\|server_url\|endpoint\|feedUrl\|feed_url\
\|appcastUrl\|updateUrl\|hostUrl\|apiUrl\|wsUrl\|mqttHost\|brokerUrl\|serverAddress" \
  --include="*.dart" --include="*.yaml" -l -i
```

**若命中** → 记录为"可配置端点信号"，继续 Step 1c。

---

### Step 1c — 外部直连信号检测

检测插件代码中是否存在硬编码的外部 URL（排除注释和测试文件）：

```bash
grep -rn "https\?://\|ws\?://" --include="*.dart" \
  | grep -v "example\|test\|_test\|\.g\.dart\|//" \
  | head -20
```

**若命中非厂商固定域名的外部 URL** → 记录为"外部直连信号"，继续 Step 2。

---

### Step 2 — 去中心化信号检测

**检查去中心化信号**（满足任意一项 → 记录 decentralized 信号）：

```bash
# P2P / WebRTC / Mesh
grep -r "flutter_webrtc\|dart_webrtc\|webrtc\|nearby_connections\|bluetooth_mesh\|wifi_direct\|p2p\|meshnetwork" \
  --include="*.yaml" --include="*.dart" -l -i

# 自动更新框架（URL 可配置）
grep -r "WinSparkle\|winsparkle\|Sparkle\|sparkle_flutter\|appcast\|appcastUrl" \
  --include="*.dart" --include="*.yaml" --include="*.swift" --include="*.h" -l -i

# 自托管 / 可配置服务协议
grep -r "mqtt\|MQTT\|amqp\|stomp\|websocket.*url\|socket.*host\|oidc\|oauth2.*endpoint" \
  --include="*.dart" --include="*.yaml" -l -i

# 开放地图（无需 AppKey）
grep -r "openstreetmap\|osm\|tile\.openstreetmap\|nominatim" \
  --include="*.dart" --include="*.yaml" -l -i

# 区块链工具库（可连接任意 RPC 节点）
grep -r "web3dart\|web3\|ethers\|flutter_web3\|walletconnect" \
  --include="*.dart" --include="*.yaml" -l -i

# 自托管 BaaS
grep -r "appwrite" --include="*.dart" --include="*.yaml" -l -i
```

去中心化判定条件（满足任意一项）：
- WebRTC SDK（`flutter_webrtc`、`dart_webrtc`）
- 蓝牙 Mesh / 附近发现（`nearby_connections`、`bluetooth_mesh`）
- Wi-Fi Direct / P2P 直连
- 自动更新框架且端点可配置（WinSparkle、Sparkle）
- MQTT / AMQP / STOMP 等可自托管协议客户端
- 通用 WebSocket/SSE 客户端（目标 URL 可配置）
- 开放协议 OAuth2/OIDC（不绑定特定厂商）
- 开放地图 tile（OpenStreetMap 等无需注册）
- 区块链 / Web3 工具库（`web3dart`、`ethers`、`walletconnect`）
- 自托管 BaaS（`appwrite`）
- Step 1b/1c 存在可配置端点信号且无特定厂商绑定

---

### Step 3 — 最终判定

按以下优先级决定 topology：

1. **Step 1a 命中厂商信号** → `centralized`
2. **Step 2 命中去中心化信号** → `decentralized`（若同时命中 Step 1a，仍为 `centralized`）
3. **Step 1b 或 Step 1c 有可配置端点 / 外部 URL 信号，且无厂商绑定** → `decentralized`
4. **无任何网络调用迹象** → `pure_edge`
5. **仅有 http/dio 等工具包但插件自身未调用任何外部端点** → `pure_edge`

---

## Output

```json
{
  "topology": "pure_edge | centralized | decentralized",
  "label": "纯端 | 端云协同中心化 | 端云协同去中心化",
  "services": [
    {
      "name": "友盟推送",
      "provider": "友盟",
      "provider_en": "Umeng"
    },
    {
      "name": "Firebase Analytics",
      "provider": "Google",
      "provider_en": "Google"
    }
  ],
  "evidence": ["具体文件和代码行", "..."]
}
```

**`evidence` 填写规范**：
- 必须是 grep 命中的**文件路径和代码行**，例如 `pubspec.yaml:12 (agora_rtc_engine: ^6.2.0)`、`android/build.gradle:8 (com.huawei.agconnect)`
- **禁止**填写功能描述或插件用途说明（那是 features-check 的职责）
- `topology=pure_edge` 时无 grep 命中，evidence 填写各步扫描结论：
  ```
  ["Step 1a: 无厂商信号命中", "Step 1b: 无可配置端点信号", "Step 1c: 无外部 URL", "Step 2: 无去中心化信号"]
  ```

> `services` 为空数组时 topology 应为 `pure_edge` 或 `decentralized`。
> decentralized 类服务（WebRTC、MQTT、OpenStreetMap 等）不计入 services，仅在 evidence 中记录。
