#!/bin/bash
# 测试数据注入脚本
# 用法: ./test_data.sh [后端地址]
# 默认: http://localhost:8000

BASE_URL="${1:-http://localhost:8000}"
echo "后端地址: $BASE_URL"
echo "========================================="

# 1. 注入多条测试告警（不同观察点、不同级别）
echo ""
echo "[1] 注入测试告警..."

# link_status - ERROR（会触发关键事件 banner）
curl -s -X POST "$BASE_URL/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "alert",
    "observer_name": "link_status",
    "level": "error",
    "message": "端口 eth0 link DOWN (测试)",
    "details": {"port": "eth0", "prev_state": "up", "new_state": "down"}
  }' && echo " ✓ link_status ERROR"

sleep 0.3

# error_code - WARNING
curl -s -X POST "$BASE_URL/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "alert",
    "observer_name": "error_code",
    "level": "warning",
    "message": "PCIe 错误计数增加: correctable +5",
    "details": {"category": "pcie", "counter": "correctable", "delta": 5}
  }' && echo " ✓ error_code WARNING"

sleep 0.3

# port_error_code - ERROR（会触发关键事件 banner）
curl -s -X POST "$BASE_URL/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "alert",
    "observer_name": "port_error_code",
    "level": "error",
    "message": "FC端口 0x1100 误码增加: BadXmitBc +128",
    "details": {"port_id": "0x1100", "counter": "BadXmitBc", "delta": 128}
  }' && echo " ✓ port_error_code ERROR"

sleep 0.3

# alarm_type - WARNING
curl -s -X POST "$BASE_URL/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "alert",
    "observer_name": "alarm_type",
    "level": "warning",
    "message": "系统告警: ETH_PORT 告警触发",
    "details": {"alarm_type": "ETH_PORT", "count": 1}
  }' && echo " ✓ alarm_type WARNING"

sleep 0.3

# abnormal_reset - ERROR（会触发关键事件 banner）
curl -s -X POST "$BASE_URL/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "alert",
    "observer_name": "abnormal_reset",
    "level": "error",
    "message": "检测到异常复位: 最近 1 次",
    "details": {"reset_count": 1, "last_reset_time": "2026-03-04 10:30:00"}
  }' && echo " ✓ abnormal_reset ERROR"

sleep 0.3

# error_code - INFO（丢包，降级后的）
curl -s -X POST "$BASE_URL/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "alert",
    "observer_name": "error_code",
    "level": "info",
    "message": "端口统计信息: eth0 rx_dropped +10",
    "details": {"category": "dropped", "port": "eth0", "counter": "rx_dropped", "delta": 10}
  }' && echo " ✓ error_code INFO (丢包)"

echo ""
echo "[1] 完成! 已注入 6 条测试告警"

# 2. 创建系统告警
echo ""
echo "[2] 注入系统告警..."
curl -s -X POST "$BASE_URL/api/system-alerts/test?level=warning&message=测试系统告警" && echo " ✓ 系统告警"
curl -s -X POST "$BASE_URL/api/system-alerts/test?level=error&message=模拟数据库表缺失错误" && echo " ✓ 系统错误"

echo ""
echo "========================================="
echo "测试数据注入完成!"
echo ""
echo "接下来请在浏览器中："
echo "1. 打开告警中心查看新告警"
echo "2. 顶部应出现关键事件 banner (3个 ERROR 级别)"
echo "3. 点击「全部忽略 24 小时」测试抑制功能"
echo "4. 抑制后应出现灰色抑制状态条"
echo ""
echo "浏览器控制台测试（可选）:"
cat << 'EOF'
// 手动添加抑制（测试取消功能）
const store = window.__pinia._s.get('alerts')
store.suppressedObservers = new Map([
  ['link_status', Date.now() + 3600000],
  ['error_code', Date.now() + 7200000],
  ['port_error_code', Date.now() + 86400000]
])

// 手动添加关键事件（测试 banner）
store.criticalEvents = [
  { id: 999, observer_name: 'test_observer', message: '手动测试关键事件', level: 'error' }
]
EOF
