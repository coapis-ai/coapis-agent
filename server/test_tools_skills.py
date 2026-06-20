# -*- coding: utf-8 -*-
"""验证工具、技能的触发及执行机制"""

import asyncio
import sys
from pathlib import Path

# Add server to path
sys.path.insert(0, str(Path(__file__).parent))

from coapis.tools.registry import ToolRegistry, TOOL_GROUPS
from coapis.tools.builtin import register_builtin_tools
from coapis.skills.manager import SkillManager


async def test_tool_registry():
    """测试工具注册表"""
    print("=" * 60)
    print("🔧 测试工具注册表")
    print("=" * 60)
    
    registry = ToolRegistry()
    
    # 注册内置工具
    register_builtin_tools(registry)
    
    tools = registry.list_tools()
    print(f"✅ 已注册工具数量: {len(tools)}")
    
    # 显示工具列表
    print("\n📋 工具列表:")
    for tool in tools[:10]:  # 只显示前10个
        print(f"  - {tool.name}: {tool.description[:50]}...")
    
    return registry


async def test_tool_execution(registry: ToolRegistry):
    """测试工具执行"""
    print("\n" + "=" * 60)
    print("⚡ 测试工具执行")
    print("=" * 60)
    
    # 测试 1: file_read
    try:
        result = await registry.call("file_read", path="coapis/__version__.py")
        print(f"✅ file_read: 读取成功 ({len(result)} 字符)")
    except Exception as e:
        print(f"❌ file_read 失败: {e}")
    
    # 测试 2: shell_execute
    try:
        result = await registry.call("shell_execute", command="echo 'Hello from tool!'")
        print(f"✅ shell_execute: {result.strip()}")
    except Exception as e:
        print(f"❌ shell_execute 失败: {e}")
    
    # 测试 3: file_write
    try:
        test_file = "/tmp/test_tool_write.txt"
        result = await registry.call("file_write", path=test_file, content="Test content")
        print(f"✅ file_write: {result}")
    except Exception as e:
        print(f"❌ file_write 失败: {e}")
    
    # 测试 4: list_files
    try:
        result = await registry.call("list_files", path="coapis")
        print(f"✅ list_files: 找到 {len(result)} 个文件")
    except Exception as e:
        print(f"❌ list_files 失败: {e}")


async def test_tool_selection():
    """测试工具选择机制"""
    print("\n" + "=" * 60)
    print("🎯 测试工具选择机制")
    print("=" * 60)
    
    registry = ToolRegistry()
    register_builtin_tools(registry)
    
    # 测试 1: 无查询 - 返回所有工具
    all_tools = registry.get_openai_tools()
    print(f"✅ 无查询: 返回 {len(all_tools)} 个工具")
    all_names = [t["function"]["name"] for t in all_tools]
    print(f"   工具: {all_names}")
    
    # 测试 2: 搜索查询 - 检查工具组匹配
    search_tools = registry.get_openai_tools(query="帮我搜索一下天气")
    print(f"✅ 搜索查询: 返回 {len(search_tools)} 个工具")
    search_names = [t["function"]["name"] for t in search_tools]
    print(f"   工具: {search_names}")
    
    # 测试 3: 文件操作查询
    file_tools = registry.get_openai_tools(query="读取文件内容")
    print(f"✅ 文件操作查询: 返回 {len(file_tools)} 个工具")
    file_names = [t["function"]["name"] for t in file_tools]
    print(f"   工具: {file_names}")


async def test_tool_groups():
    """测试工具组配置"""
    print("\n" + "=" * 60)
    print("📦 测试工具组配置")
    print("=" * 60)
    
    for group_name, group in TOOL_GROUPS.items():
        tools_count = len(group["tools"])
        always_active = group.get("always_active", False)
        keywords = group.get("keywords", set())
        
        print(f"\n🔹 {group_name}:")
        print(f"   工具数: {tools_count}")
        print(f"   始终激活: {'✅' if always_active else '❌'}")
        if keywords:
            print(f"   关键词: {list(keywords)[:5]}...")


async def test_skill_manager():
    """测试技能管理器"""
    print("\n" + "=" * 60)
    print("🎯 测试技能管理器")
    print("=" * 60)
    
    # 使用项目根目录下的 skills
    skills_dir = Path(__file__).parent.parent.parent / "skills"
    
    if not skills_dir.exists():
        print(f"⚠️  技能目录不存在: {skills_dir}")
        print("   跳过技能测试")
        return
    
    manager = SkillManager(skills_dir)
    await manager.discover()
    
    skills = manager.list_skills()
    print(f"✅ 已发现技能数量: {len(skills)}")
    
    if skills:
        print("\n📋 技能列表 (前10个):")
        for skill in skills[:10]:
            print(f"  - {skill['name']}: {skill['description'][:60]}...")
        
        # 测试技能索引生成
        index_prompt = manager.get_index_prompt()
        print(f"\n📝 技能索引提示词长度: {len(index_prompt)} 字符")
        
        # 显示部分索引内容
        if index_prompt:
            print("\n📄 技能索引预览:")
            lines = index_prompt.split("\n")[:8]
            for line in lines:
                print(f"  {line}")
            if len(index_prompt.split("\n")) > 8:
                print("  ...")


async def main():
    """主测试函数"""
    print("🚀 CoApis 工具/技能触发及执行机制验证")
    print("=" * 60)
    
    try:
        # 测试工具注册表
        registry = await test_tool_registry()
        
        # 测试工具执行
        await test_tool_execution(registry)
        
        # 测试工具选择机制
        await test_tool_selection()
        
        # 测试工具组配置
        await test_tool_groups()
        
        # 测试技能管理器
        await test_skill_manager()
        
        print("\n" + "=" * 60)
        print("✅ 所有测试完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
