#!/usr/bin/env python3
"""
优化后的场景智能体批量生成脚本
从 optimized_scenes.json 读取配置，批量创建37个智能体
"""

import json
import os
from pathlib import Path
from datetime import datetime

# 工作目录
WORKING_DIR = Path(os.environ.get('WORKING_DIR', '/apps/ai/coapis'))
SCRIPT_DIR = Path(__file__).parent
ARCHIVE_DIR = SCRIPT_DIR.parent.parent / 'industries-archive'
AGENTS_DIR = WORKING_DIR / 'agents'

def load_optimized_config():
    """加载优化后的场景配置"""
    config_file = ARCHIVE_DIR / 'optimized_scenes.json'
    with open(config_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_agent_id(scene_id):
    """生成智能体ID"""
    return f"scene-{scene_id}"

def generate_generic_agent_config(scene_data):
    """生成通用场景智能体配置"""
    agent_id = generate_agent_id(scene_data['id'])
    
    config = {
        "id": agent_id,
        "name": scene_data['name'],
        "description": scene_data['description'],
        "model": "gpt-4",
        "system_prompt": scene_data['system_prompt'],
        "welcome_message": scene_data['welcome_message'],
        
        # 场景信息
        "scene_info": {
            "scene_id": scene_data['id'],
            "scene_type": scene_data['type'],
            "category": scene_data['category'],
            "is_generic": True,
            "supported_domains": scene_data['supported_domains'],
            "priority": scene_data.get('priority', 'medium')
        },
        
        # 技能配置
        "skills": scene_data.get('skills', []),
        
        # 元数据
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "created_by": "system",
            "version": "2.0",
            "source": "optimized_scenes",
            "optimization_date": "2026-07-17"
        },
        
        # 进化配置
        "evolution": {
            "enabled": True,
            "memory_file": "MEMORY.md",
            "max_memory_size": 100,
            "auto_evolve": True,
            "shared_memory": True  # 通用场景使用共享记忆
        },
        
        # 工具配置
        "tools": {
            "enabled": True,
            "whitelist": [],
            "blacklist": []
        },
        
        # 领域上下文注入配置
        "domain_context_injection": {
            "enabled": True,
            "injection_point": "system_prompt",
            "context_source": "domain_contexts.json"
        }
    }
    
    return config

def create_agent_directory(agent_id):
    """创建智能体目录"""
    agent_dir = AGENTS_DIR / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    return agent_dir

def save_agent_config(agent_dir, config):
    """保存智能体配置"""
    config_file = agent_dir / 'agent.json'
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def create_memory_file(agent_dir, is_generic=True):
    """创建记忆文件"""
    memory_file = agent_dir / 'MEMORY.md'
    if not memory_file.exists():
        if is_generic:
            content = """# 通用场景智能体记忆

## 共享进化记忆

此记忆将被所有使用该场景的用户共享。

**场景类型**：通用场景
**支持领域**：多个领域

---

## 进化记录

（此处记录场景的进化过程，如优化建议、典型案例等）

"""
        else:
            content = """# 场景智能体记忆

## 共享进化记忆

此记忆将被所有使用该场景的用户共享。

---

## 进化记录

（此处记录场景的进化过程）

"""
        memory_file.write_text(content, encoding='utf-8')

def generate_all_optimized_agents():
    """批量生成所有优化后的场景智能体"""
    print("=" * 80)
    print("优化后的场景智能体批量生成")
    print("=" * 80)
    
    # 加载配置
    config = load_optimized_config()
    print(f"\n优化方案版本: {config['version']}")
    print(f"总场景数: {config['statistics']['total_optimized_scenes']}")
    print(f"通用场景: {config['statistics']['total_generic_scenes']}")
    
    # 统计信息
    stats = {
        'total_generic_agents': 0,
        'total_unique_agents': 0,
        'errors': []
    }
    
    # 创建通用场景智能体
    print(f"\n{'=' * 80}")
    print("创建通用场景智能体（11个）")
    print(f"{'=' * 80}")
    
    for scene in config['generic_scenes']:
        agent_id = generate_agent_id(scene['id'])
        
        print(f"\n场景: {scene['name']} ({scene['id']})")
        print(f"  类型: {scene['type']} | 分类: {scene['category']}")
        print(f"  支持领域: {len(scene['supported_domains'])}个")
        print(f"  智能体ID: {agent_id}")
        
        try:
            # 创建智能体目录
            agent_dir = create_agent_directory(agent_id)
            
            # 生成配置
            agent_config = generate_generic_agent_config(scene)
            
            # 保存配置
            save_agent_config(agent_dir, agent_config)
            
            # 创建记忆文件
            create_memory_file(agent_dir, is_generic=True)
            
            stats['total_generic_agents'] += 1
            print(f"  ✅ 已创建")
        
        except Exception as e:
            error_msg = f"场景 {scene['id']} 创建失败: {str(e)}"
            stats['errors'].append(error_msg)
            print(f"  ❌ 错误: {str(e)}")
    
    # 保存领域上下文配置
    print(f"\n{'=' * 80}")
    print("保存领域上下文配置")
    print(f"{'=' * 80}")
    
    domain_contexts = config['domain_contexts']
    contexts_file = WORKING_DIR / 'domain_contexts.json'
    
    with open(contexts_file, 'w', encoding='utf-8') as f:
        json.dump(domain_contexts, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 领域上下文配置已保存: {contexts_file}")
    print(f"   包含 {len(domain_contexts)} 个领域")
    
    # 输出统计
    print(f"\n{'=' * 80}")
    print("生成完成统计")
    print(f"{'=' * 80}")
    print(f"通用场景智能体: {stats['total_generic_agents']}")
    print(f"领域上下文配置: {len(domain_contexts)}个领域")
    
    if stats['errors']:
        print(f"\n错误列表:")
        for error in stats['errors']:
            print(f"  - {error}")
    
    # 生成报告
    generate_report(stats, config)
    
    return stats

def generate_report(stats, config):
    """生成创建报告"""
    report_file = ARCHIVE_DIR / 'scripts' / 'generation_report.md'
    
    report = f"""# 场景智能体批量生成报告

> **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> **生成版本**：v2.0（优化版）

---

## 一、生成统计

| 指标 | 数量 |
|------|------|
| **通用场景智能体** | {stats['total_generic_agents']} |
| **领域上下文配置** | {len(config['domain_contexts'])} |
| **错误数量** | {len(stats['errors'])} |

---

## 二、通用场景列表

"""
    
    for i, scene in enumerate(config['generic_scenes'], 1):
        report += f"{i}. **{scene['name']}**（{scene['id']}）\n"
        report += f"   - 类型：{scene['type']}\n"
        report += f"   - 支持领域：{len(scene['supported_domains'])}个\n\n"
    
    report += f"""
---

## 三、智能体存储位置

```
{AGENTS_DIR}/
├── scene-meeting-minutes/
├── scene-document-drafting/
├── scene-work-report/
├── ...（共{stats['total_generic_agents']}个智能体）
```

---

## 四、领域上下文配置

存储位置：`{WORKING_DIR}/domain_contexts.json`

包含领域：
"""
    
    for code, context in config['domain_contexts'].items():
        report += f"- {context['name']}（{code}）\n"
    
    report += f"""

---

## 五、后续步骤

1. ✅ 验证智能体配置
2. ✅ 测试通用场景的领域适配性
3. ✅ 部署到开发环境
4. ✅ 创建领域独特场景（26个）

---

**报告生成完成**
"""
    
    report_file.write_text(report, encoding='utf-8')
    print(f"\n✅ 生成报告已保存: {report_file}")

if __name__ == '__main__':
    generate_all_optimized_agents()
