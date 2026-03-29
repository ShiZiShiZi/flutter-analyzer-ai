#!/bin/bash
while true; do
    done_count=$(python3 -c "
import sqlite3
conn = sqlite3.connect('/workspace/projects/workspace/flutter-analyzer-ai/plugins.db')
c = conn.cursor()
c.execute(\"SELECT COUNT(DISTINCT plugin_id) FROM analysis_runs WHERE status='done'\")
print(c.fetchone()[0])
conn.close()
")
    
    running=$(python3 -c "
import sqlite3
conn = sqlite3.connect('/workspace/projects/workspace/flutter-analyzer-ai/plugins.db')
c = conn.cursor()
c.execute(\"SELECT COUNT(*) FROM analysis_runs WHERE status='running'\")
print(c.fetchone()[0])
conn.close()
")
    
    calls=$(curl -s http://localhost:8100/api/providers/stats 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d['call_counts']['tencent'])
except:
    print(0)
")
    
    errors=$(curl -s http://localhost:8100/api/providers/stats 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d['error_counts']['tencent'])
except:
    print(0)
")
    
    timestamp=$(date +%H:%M:%S)
    echo "[$timestamp] 完成: $done_count | 运行: $running | API: $calls | 错误: $errors"
    
    # 每60秒检查一次
    sleep 60
done
