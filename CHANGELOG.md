# 更新日志

## 2025-03-29 - 多 Provider 支持与并发优化

### 主要修改

#### 1. 智能代理系统 (`src/proxy.py`)
- 新增 `ProviderPool` 类，支持多 API Provider 自动切换
- 检测 429/限流响应时自动切换到下一个 provider
- 记录每个 provider 的调用次数和错误次数
- 配置文件: `providers.json`

#### 2. 分析器优化 (`src/analyzer.py`)
- 使用全局代理端口 8765（与 web/app.py 保持一致）
- 优化 opencode 工作目录配置
- 增强日志输出，便于调试

#### 3. Web 服务 (`web/app.py`)
- 新增 `/api/providers/stats` 端点，查看多 Provider 统计
- 使用固定代理端口 8765
- 改进服务重启时的状态恢复

#### 4. 并发控制 (`web/queue.py`)
- `CONCURRENCY` 从 20 调整为 5
- 适配 4GB 内存环境，每个 opencode 进程约占用 350MB

### 新增文件

| 文件 | 说明 |
|------|------|
| `providers.json` | 多 Provider 配置（腾讯百炼 + 阿里云百炼） |
| `monitor.sh` | 简单监控脚本 |

### 配置说明

#### providers.json 格式
```json
{
  "providers": [
    {
      "name": "tencent",
      "base_url": "https://api.lkeap.tencent.com/v1",
      "api_key": "${TENCENT_API_KEY}"
    },
    {
      "name": "aliyun-1",
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "api_key": "${ALIYUN_API_KEY_1}"
    }
  ]
}
```

#### 环境变量
- `TENCENT_API_KEY`: 腾讯百炼 API Key
- `ALIYUN_API_KEY_1`, `ALIYUN_API_KEY_2`: 阿里云百炼 API Key

### 部署步骤（新环境）

1. 克隆代码
```bash
git clone https://github.com/ShiZiShiZi/flutter-analyzer-ai.git
cd flutter-analyzer-ai
```

2. 安装依赖
```bash
pip install -r requirements.txt  # 或 pyproject.toml
```

3. 配置 Provider
```bash
# 创建 providers.json
cat > providers.json << 'EOF'
{
  "providers": [
    {
      "name": "tencent",
      "base_url": "https://api.lkeap.tencent.com/v1",
      "api_key": "your-tencent-api-key"
    }
  ]
}
EOF
```

4. 配置 opencode
```bash
# 确保 ~/.config/opencode/opencode.json 存在且配置了 bailian-coding-plan provider
# 代理会将其 baseURL 指向 http://127.0.0.1:8765
```

5. 启动服务
```bash
uvicorn web.app:app --host 0.0.0.0 --port 8100
```

6. 导入插件并开始分析
```bash
# 访问 http://localhost:8100/import 批量导入插件
# 或通过 API 添加任务
```

### 资源需求

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| 内存 | 4GB+ | 5并发约需 2GB |
| 磁盘 | 20GB+ | 1000+ 插件源码 |
| 并发数 | 3-5 | 根据内存调整 |
