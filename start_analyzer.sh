#!/bin/bash
# Flutter Analyzer 自动启动脚本
# 用于开机自启动和崩溃后自动恢复

PROJECT_DIR="/workspace/projects/workspace/flutter-analyzer-ai"
LOG_DIR="$PROJECT_DIR/logs"
PID_FILE="$PROJECT_DIR/analyzer.pid"

cd $PROJECT_DIR

# 创建日志目录
mkdir -p $LOG_DIR

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> $LOG_DIR/startup.log
}

log "========== Flutter Analyzer 启动 =========="

# 检查服务是否已在运行
if curl -s http://localhost:8100/api/providers/stats > /dev/null 2>&1; then
    log "服务已在运行，跳过启动"
    exit 0
fi

# 清理残留进程
pkill -f "uvicorn web.app:app" 2>/dev/null
sleep 2

# 启动 uvicorn 服务
log "启动 uvicorn 服务..."
/usr/bin/python3 /usr/local/bin/uvicorn web.app:app --host 0.0.0.0 --port 8100 >> $LOG_DIR/uvicorn.log 2>&1 &
UVICORN_PID=$!
echo $UVICORN_PID > $PID_FILE

log "uvicorn 启动 (PID: $UVICORN_PID)"

# 等待服务启动
for i in {1..30}; do
    if curl -s http://localhost:8100/api/providers/stats > /dev/null 2>&1; then
        log "uvicorn 服务就绪"
        break
    fi
    sleep 1
done

# 检查服务是否正常
if ! curl -s http://localhost:8100/api/providers/stats > /dev/null 2>&1; then
    log "错误: uvicorn 启动失败"
    exit 1
fi

# 添加未完成的任务到队列
log "添加未完成任务到队列..."
python3 << 'PYTHON_SCRIPT'
import sqlite3
import requests
import sys

try:
    conn = sqlite3.connect('/workspace/projects/workspace/flutter-analyzer-ai/plugins.db')
    c = conn.cursor()

    c.execute("SELECT DISTINCT plugin_id FROM analysis_runs WHERE status='done'")
    done_plugins = set(r[0] for r in c.fetchall())

    c.execute("SELECT id FROM plugins ORDER BY id")
    all_plugins = [r[0] for r in c.fetchall()]

    pending_plugins = [p for p in all_plugins if p not in done_plugins]
    print(f"未完成插件数: {len(pending_plugins)}")

    batch_size = 100
    total_added = 0

    for i in range(0, len(pending_plugins), batch_size):
        batch = pending_plugins[i:i+batch_size]
        try:
            resp = requests.post("http://localhost:8100/api/plugins/analyze-batch", 
                                 json={"plugin_ids": batch, "force": False}, timeout=30)
            if resp.status_code == 200:
                total_added += len(resp.json().get("run_ids", []))
        except Exception as e:
            print(f"批次错误: {e}")

    conn.close()
    print(f"已添加 {total_added} 个任务到队列")
except Exception as e:
    print(f"添加任务错误: {e}")
    sys.exit(1)
PYTHON_SCRIPT

if [ $? -eq 0 ]; then
    log "任务已添加到队列"
else
    log "添加任务失败"
fi

# 启动监控脚本
if ! pgrep -f "monitor.sh" > /dev/null; then
    log "启动监控脚本..."
    nohup bash $PROJECT_DIR/monitor.sh >> $LOG_DIR/monitor.log 2>&1 &
fi

log "Flutter Analyzer 启动完成"
