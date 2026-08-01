#!/bin/bash
# 监控场景会话创建

echo "=== 场景会话监控 ==="
echo "按 Ctrl+C 停止"
echo ""

while true; do
    echo "[$(date '+%H:%M:%S')] 检查聊天列表..."
    
    # 查找 scene- 开头的聊天
    scene_chats=$(cat /apps/ai/coapis/workspaces/admin/chat/chats.json | jq -r '.chats[] | select(.id | startswith("scene-")) | "\(.id) | \(.name) | \(.scene_id)"')
    
    if [ -n "$scene_chats" ]; then
        echo "✅ 发现场景聊天："
        echo "$scene_chats" | while read line; do
            echo "   $line"
        done
        break
    else
        echo "⏳ 等待场景聊天创建..."
    fi
    
    sleep 2
done

echo ""
echo "=== 监控结束 ==="
