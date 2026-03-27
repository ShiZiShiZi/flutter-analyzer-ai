---
name: payment-check
description: "Detect payment, monetization, and paid cloud service dependencies in a Flutter plugin codebase"
metadata:
  category: "flutter-analysis"
---

## Goal
分析 Flutter 插件两个维度的付费情况：
1. **插件本身是否收费**（商业许可证、双重授权、需要购买激活码）
2. **使用插件需要付费的云服务**（付费云端后端依赖）

**路径约定**：以下所有命令均需在仓库根目录下执行，或显式指定仓库路径。

## Steps

### Step 1：检查插件本身是否收费（plugin_paid）

```bash
grep -i "proprietary\|All Rights Reserved\|not free for commercial use\|commercial use requires\|dual license\|dual-licensed\|license key\|activation key\|pricing\|商业授权\|购买授权\|授权码" \
  LICENSE* README* pubspec.yaml 2>/dev/null | head -40
```

**信号判断**：
- 出现 `proprietary`、`All Rights Reserved`、`not free for commercial use` → `commercial_license`
- 出现 `dual license` / `dual-licensed` 且同时含 `GPL` + (`commercial` 或 `enterprise`) → `commercial_license`
- 出现 `license key`、`activation key`、`pricing`、`商业授权`、`授权码` → `commercial_license`

> 若前序 license-check 结论为 `category=proprietary`，可直接判定 `plugin_paid=true`，跳过本步扫描。

---

### Step 2：检查付费云服务依赖

**2a. 读取 pubspec.yaml，匹配已知付费服务包名**

```bash
cat pubspec.yaml 2>/dev/null
```

按如下分类判断（匹配 dependencies / dev_dependencies 中的包名）：

| 分类 | 包名关键词 | payment_type |
|---|---|---|
| 内购/订阅管理 | `in_app_purchase`、`flutter_inapp_purchase`、`purchases_flutter`、`superwallkit_flutter`、`adapty_flutter`、`qonversion_flutter` | `in_app_purchase` / `subscription_management` |
| 支付处理（国际） | `stripe_flutter`、`flutter_stripe`、`pay`、`razorpay_flutter`、`paytm`、`braintree` | `payment_processing` |
| 支付处理（国内） | `alipay_kit`、`wxpay`、`wechat_kit`、`unionpay`、`flutter_alipay` | `payment_processing` |
| 广告变现 | `google_mobile_ads`、`facebook_audience_network`、`unity_ads`、`applovin_max` | `ad_monetization` |
| 实时音视频 RTC | `agora_rtc_engine`、`zego_express_engine`、`trtc_cloud_flutter`、`vonage_client_sdk` | `real_time_communication` |
| 即时通讯 IM | `stream_chat_flutter`、`sendbird_sdk`、`tencent_im_plugin`、`tim_ui_kit`、`netease_corekit_nim`、`rongcloud_sdk_flutter_plugin` | `paid_cloud_service` |
| 推送通知 | `onesignal_flutter`、`jpush_flutter`、`getui_flutter_plugin`、`aliyun_push` | `paid_cloud_service` |
| 归因/营销分析 | `appsflyer_sdk`、`adjust_sdk`、`flutter_branch_sdk` | `attribution_analytics` |
| 用户行为分析 | `mixpanel_flutter`、`amplitude_flutter`、`segment_analytics_flutter`、`braze_plugin` | `paid_cloud_service` |
| 监控/APM | `sentry_flutter`、`datadog_flutter_plugin` | `paid_cloud_service` |
| 地图服务 | `google_maps_flutter`、`mapbox_gl`、`mapbox_maps_flutter`、`amap_flutter_map`、`amap_map_fluttify`、`flutter_baidu_mapapi_map`、`tencent_map_flutter` | `paid_cloud_service` |
| AI/ML API | `dart_openai`、`openai`、`iflytek_flutter`、`flutter_iflytek`、`baidu_aip` | `paid_cloud_service` |
| 国内云存储 | `qiniu_dart_sdk`、`tencent_cos_sdk`、`aliyun_oss_dart` | `paid_cloud_service` |
| 国际云平台 | `aws_amplify`、`supabase_flutter` | `paid_cloud_service` |
| 短信/邮件 | `twilio_flutter`、`sendgrid_mailer` | `paid_cloud_service` |

**2b. 检查 Android/iOS 原生依赖**

```bash
cat android/build.gradle 2>/dev/null | grep -i "implementation\|classpath\|maven" | head -20
grep -E "s\.dependency|s\.frameworks" ios/*.podspec 2>/dev/null | head -20
```

**2c. 检查 example 目录下的初始化代码（API key 配置集中处）**

```bash
grep -r "ApiKey\|APP_KEY\|APP_SECRET\|APPID\|apiKey\|secretKey\|accessKey\|appkey\|AppId\|appId" \
  example/ --include="*.dart" --include="*.java" --include="*.kt" --include="*.swift" -l 2>/dev/null | head -10
```

---

### Step 3：源码 grep 补充扫描

```bash
# 付费服务 API Key 配置信号（插件主体代码，排除 example/）
grep -r "ApiKey\|APP_KEY\|APP_SECRET\|APPID\|apiKey\|secretKey\|accessKey\|appkey" \
  lib/ android/src/ ios/Classes/ \
  --include="*.dart" --include="*.java" --include="*.kt" --include="*.swift" -l 2>/dev/null | head -10

# 定价相关文案（README）
grep -i "pricing\|free tier\|quota\|rate limit\|enterprise\|商业授权\|收费\|付费\|按量" README* 2>/dev/null | head -20

# 内购/支付核心 API 调用（精确模式，避免宽泛词误报）
grep -r "RevenueCat\.configure\|Purchases\.configure\|StoreKit\|BillingClient\|InAppPurchase\|paywall\|Superwall\|AppsFlyer\|Adjust\.appToken\|AgoraRtcEngine\|ZegoExpressEngine" \
  --include="*.dart" --include="*.java" --include="*.kt" --include="*.swift" -l 2>/dev/null | head -10
```

---

## Output

```json
{
  "involves_payment": true,
  "plugin_paid": false,
  "cloud_paid": true,
  "payment_type": ["payment_processing", "paid_cloud_service"],
  "evidence": ["pubspec.yaml:12 (alipay_kit: ^1.2.0)", "android/build.gradle:28 (com.alipay.sdk:alipaysdk-android)"]
}
```

**字段说明**：
- `involves_payment`：`plugin_paid` 或 `cloud_paid` 任一为 true 则为 true
- `plugin_paid`：插件本身需购买授权时为 true（Step 1 命中）
- `cloud_paid`：插件功能依赖付费云端服务时为 true（Step 2/3 命中）
- `payment_type`：仅填写实际命中的枚举值，枚举范围：
  - `commercial_license`：插件本身需购买商业授权
  - `paid_cloud_service`：依赖付费云端服务（IM、推送、地图、AI 等）
  - `in_app_purchase`：集成 App 内购买（StoreKit / BillingClient）
  - `subscription_management`：订阅/Paywall 管理工具（RevenueCat、Superwall 等）
  - `payment_processing`：支付处理（Stripe、支付宝、微信支付等）
  - `ad_monetization`：广告变现 SDK
  - `real_time_communication`：实时音视频（Agora/ZEGO，按分钟计费）
  - `attribution_analytics`：归因/营销分析工具（AppsFlyer、Adjust）
