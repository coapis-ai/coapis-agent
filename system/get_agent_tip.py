#!/usr/bin/env python3
"""
CoApis 智能体提示语获取器
调用一次，返回一条符合当前时间的提示语。
无需参数，自动根据当前时间/星期过滤。
"""

import json
import random
import os
from datetime import datetime


def _load_tips():
    """加载提示语 JSON 文件"""
    tips_path = os.path.join(os.path.dirname(__file__), "agent_tips.json")
    with open(tips_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_time_match(tip, current_hour, current_weekday, data):
    """
    判断一条提示语是否符合当前时间约束。

    Args:
        tip: 提示语字典
        current_hour: 当前小时 (0-23)
        current_weekday: 当前星期 (0=周一, 6=周日)
        data: 完整的 JSON 数据（含 time_periods, weekdays）

    Returns:
        bool: 是否符合时间约束
    """
    tc = tip.get("time_constraint")
    if tc is None:
        return True  # 无限制，随时可用

    # 时间范围判断
    tr = tc.get("time_range")
    if tr:
        start, end = tr["start"], tr["end"]
        if start < end:
            # 普通范围: 6~12
            if not (start <= current_hour < end):
                return False
        else:
            # 跨天范围: 23~6
            if not (current_hour >= start or current_hour < end):
                return False

    # 星期类型判断
    weekday_type = tc.get("weekday_type")
    if weekday_type:
        valid_days = data["weekdays"][weekday_type]["days"]
        if current_weekday not in valid_days:
            return False

    # 具体周几判断（可选）
    day_of_week = tc.get("day_of_week")
    if day_of_week is not None:
        if current_weekday != day_of_week:
            return False

    return True


def get_tip():
    """
    获取一条符合当前时间的智能体提示语。

    无需参数，自动根据当前系统时间过滤。
    返回格式: {"id": int, "text": str, "emoji": str, "category": str, "scene": str}

    Example:
        >>> tip = get_tip()
        >>> print(f"{tip['emoji']} {tip['text']}")
        🌅 早上好！新的一周开始了，有什么需要我帮忙的？
    """
    data = _load_tips()
    now = datetime.now()
    current_hour = now.hour
    # Python weekday(): 0=周一, 6=周日
    current_weekday = now.weekday()

    # 过滤符合条件的提示语
    candidates = [
        tip for tip in data["all_tips"]
        if _is_time_match(tip, current_hour, current_weekday, data)
    ]

    if not candidates:
        # 兜底：返回无时间约束的提示语
        candidates = [
            tip for tip in data["all_tips"]
            if tip.get("time_constraint") is None
        ]

    # 随机选一条
    tip = random.choice(candidates)

    return {
        "id": tip["id"],
        "text": tip["text"],
        "emoji": tip["emoji"],
        "category": tip["category"],
        "scene": tip["scene"],
    }


# 方便直接运行测试
if __name__ == "__main__":
    print("🐝 CoApis 智能体提示语获取器\n")
    print("=" * 50)
    for i in range(5):
        tip = get_tip()
        print(f"\n第 {i + 1} 次调用:")
        print(f"  {tip['emoji']} {tip['text']}")
        print(f"  分类: {tip['category']} | 场景: {tip['scene']}")
    print("\n" + "=" * 50)
