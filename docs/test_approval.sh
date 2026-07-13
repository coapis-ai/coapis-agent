#!/bin/bash
# 审批功能测试脚本

echo "========================================="
echo "审批功能测试"
echo "========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 1. 检查后端日志
echo -e "${YELLOW}步骤 1: 检查后端日志${NC}"
echo "请在新终端中运行以下命令查看实时日志："
echo "  docker logs -f coapis-server 2>&1 | grep -E 'APPROVAL|PUSH MESSAGES'"
echo ""

# 2. 检查前端控制台
echo -e "${YELLOW}步骤 2: 打开浏览器控制台${NC}"
echo "在浏览器中按 F12 打开开发者工具，切换到 Console 标签"
echo ""

# 3. 发送测试命令
echo -e "${YELLOW}步骤 3: 发送测试命令${NC}"
echo "在聊天中输入：帮我写一份测试文档"
echo ""

# 4. 观察日志输出
echo -e "${YELLOW}步骤 4: 观察后端日志输出${NC}"
echo -e "期望看到："
echo "  ${GREEN}[APPROVAL] Session context: current_chat_id=xxx, ...${NC}"
echo "  ${GREEN}[APPROVAL] Using root_session_id=xxx for approval request${NC}"
echo "  ${GREEN}[APPROVAL] Created pending approval: request_id=xxx, session_id=xxx, root_session_id=xxx${NC}"
echo "  ${GREEN}[PUSH MESSAGES] Total pending approvals: 1${NC}"
echo ""

# 5. 检查前端控制台
echo -e "${YELLOW}步骤 5: 检查前端控制台输出${NC}"
echo -e "期望看到："
echo "  ${GREEN}[Approval] Filtering approvals: currentSessionId=xxx, chatId=xxx${NC}"
echo "  ${GREEN}[Approval] After filtering: 1 approval(s)${NC}"
echo ""

# 6. 验证审批Card显示
echo -e "${YELLOW}步骤 6: 验证审批Card显示${NC}"
echo -e "期望结果："
echo "  ${GREEN}✓ 页面显示审批Card（带 Approve/Deny 按钮）${NC}"
echo "  ${GREEN}✓ 输入框可以正常发送消息${NC}"
echo ""

# 7. 故障排查
echo -e "${YELLOW}如果审批Card未显示，检查以下内容：${NC}"
echo ""
echo -e "${RED}问题 1: Session ID 不匹配${NC}"
echo "后端日志：[APPROVAL] root_session_id=xxx"
echo "前端日志：currentSessionId=xxx"
echo "这两个值应该相同！"
echo ""

echo -e "${RED}问题 2: 审批创建失败${NC}"
echo "后端日志：Tool 'xxx' requires approval..."
echo "但没有后续的 [APPROVAL] Created pending approval"
echo "说明审批创建失败，检查 ApprovalService 初始化"
echo ""

echo -e "${RED}问题 3: 前端轮询失败${NC}"
echo "前端控制台没有 [Approval] Filtering approvals 日志"
echo "说明 ConsolePollService 未启动或轮询失败"
echo ""

# 8. 临时解决方案
echo -e "${YELLOW}临时解决方案：${NC}"
echo "1. 降低审批级别：修改 system/tool_guard.json 中的 execution_level 为 'guard'"
echo "2. 手动批准：在聊天中输入 /approve"
echo "3. 禁用审批：修改 system/tool_guard.json 中的 execution_level 为 'off'"
echo ""

echo "========================================="
echo "测试完成"
echo "========================================="
