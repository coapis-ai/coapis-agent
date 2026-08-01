#!/usr/bin/env python3
"""
领域专属场景生成脚本
生成26个领域专属场景配置
"""

import json
from pathlib import Path
from datetime import datetime

# 专属场景数据
DOMAIN_SPECIFIC_SCENES = [
    # 自然资源领域（3个）
    {
        "id": "real-estate-registration",
        "name": "不动产登记",
        "description": "不动产登记业务辅助，支持不动产登记申请、审核、发证等流程",
        "agent_id": "scene-real-estate-registration",
        "icon": "🏠",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["natural-resources"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["document-analysis", "workflow"],
        "welcome_message": "您好！我可以帮您：\n• 不动产登记流程指导\n• 登记材料审核\n• 登记进度查询\n\n请告诉我登记类型和申请人信息。",
        "tags": {
            "features": ["流程规范", "材料审核", "进度查询"],
            "keywords": ["不动产", "登记", "房产"]
        }
    },
    {
        "id": "geological-disaster-inspection",
        "name": "地灾排查",
        "description": "地质灾害隐患排查辅助，支持地灾点巡查、风险评估、预警监测",
        "agent_id": "scene-geological-disaster-inspection",
        "icon": "⛰️",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["natural-resources"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "high"
        },
        "skills": ["gis", "image-analysis", "data-analysis"],
        "welcome_message": "您好！我可以帮您：\n• 地灾隐患点排查\n• 风险评估分析\n• 预警监测建议\n\n请告诉我排查区域和类型。",
        "tags": {
            "features": ["GIS分析", "风险评估", "预警监测"],
            "keywords": ["地质灾害", "排查", "隐患"]
        }
    },
    {
        "id": "mine-supervision",
        "name": "矿山监管",
        "description": "矿山开发监管辅助，支持矿山巡查、违规开采识别、生态修复监督",
        "agent_id": "scene-mine-supervision",
        "icon": "⛏️",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["natural-resources"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "medium"
        },
        "skills": ["gis", "image-analysis", "document-analysis"],
        "welcome_message": "您好！我可以帮您：\n• 矿山巡查监管\n• 违规开采识别\n• 生态修复监督\n\n请告诉我矿山名称和监管类型。",
        "tags": {
            "features": ["遥感监测", "违规识别", "生态修复"],
            "keywords": ["矿山", "监管", "开采"]
        }
    },
    
    # 生态环境领域（2个）
    {
        "id": "eia-approval",
        "name": "环评审批",
        "description": "环境影响评价审批辅助，支持环评报告审核、审批流程指导",
        "agent_id": "scene-eia-approval",
        "icon": "🌍",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["ecological-environment"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["document-analysis", "compliance-check"],
        "welcome_message": "您好！我可以帮您：\n• 环评报告审核\n• 审批流程指导\n• 审批进度查询\n\n请告诉我项目类型和环评阶段。",
        "tags": {
            "features": ["报告审核", "流程规范", "合规检查"],
            "keywords": ["环评", "审批", "环境影响"]
        }
    },
    {
        "id": "environmental-monitoring",
        "name": "环境监测",
        "description": "环境质量监测分析，支持空气、水质、土壤等环境指标监测",
        "agent_id": "scene-environmental-monitoring",
        "icon": "🌡️",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["ecological-environment"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["data-analysis", "visualization", "real-time-monitoring"],
        "welcome_message": "您好！我可以帮您：\n• 环境质量监测\n• 污染预警分析\n• 监测报告生成\n\n请告诉我监测类型和区域。",
        "tags": {
            "features": ["实时监测", "污染预警", "数据分析"],
            "keywords": ["环境", "监测", "污染"]
        }
    },
    
    # 农业农村领域（3个）
    {
        "id": "rural-revitalization-planning",
        "name": "振兴规划",
        "description": "乡村振兴规划编制辅助，支持村庄规划、产业发展规划等",
        "agent_id": "scene-rural-revitalization-planning",
        "icon": "🏘️",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["agriculture-rural"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "high"
        },
        "skills": ["document-analysis", "data-analysis", "gis"],
        "welcome_message": "您好！我可以帮您：\n• 乡村振兴规划编制\n• 产业发展规划\n• 规划文本撰写\n\n请告诉我规划类型和村庄信息。",
        "tags": {
            "features": ["规划编制", "产业发展", "GIS支持"],
            "keywords": ["乡村振兴", "规划", "村庄"]
        }
    },
    {
        "id": "agricultural-quality-certification",
        "name": "质量认证",
        "description": "农产品质量认证辅助，支持三品一标认证、有机认证等",
        "agent_id": "scene-agricultural-quality-certification",
        "icon": "🌱",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["agriculture-rural"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "medium"
        },
        "skills": ["document-analysis", "compliance-check"],
        "welcome_message": "您好！我可以帮您：\n• 质量认证申请\n• 认证材料准备\n• 认证进度查询\n\n请告诉我认证类型和产品信息。",
        "tags": {
            "features": ["认证申请", "材料准备", "合规检查"],
            "keywords": ["质量认证", "三品一标", "有机"]
        }
    },
    {
        "id": "agricultural-technology-extension",
        "name": "技术推广",
        "description": "农业技术推广服务，支持新技术推广、技术培训组织",
        "agent_id": "scene-agricultural-technology-extension",
        "icon": "🔬",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["agriculture-rural"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "medium"
        },
        "skills": ["document-analysis", "knowledge-base"],
        "welcome_message": "您好！我可以帮您：\n• 农业技术推广\n• 技术培训组织\n• 推广效果评估\n\n请告诉我技术类型和推广区域。",
        "tags": {
            "features": ["技术推广", "培训组织", "效果评估"],
            "keywords": ["农业技术", "推广", "培训"]
        }
    },
    
    # 发展改革领域（2个）
    {
        "id": "economic-analysis",
        "name": "经济分析",
        "description": "宏观经济形势分析，支持经济运行监测、趋势预测",
        "agent_id": "scene-economic-analysis",
        "icon": "📈",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["development-reform"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["data-analysis", "visualization", "report-generation"],
        "welcome_message": "您好！我可以帮您：\n• 经济运行分析\n• 发展趋势预测\n• 分析报告生成\n\n请告诉我分析类型和时间范围。",
        "tags": {
            "features": ["数据分析", "趋势预测", "可视化"],
            "keywords": ["经济", "分析", "预测"]
        }
    },
    {
        "id": "price-monitoring",
        "name": "价格监测",
        "description": "市场价格监测分析，支持重要商品价格监测、价格预警",
        "agent_id": "scene-price-monitoring",
        "icon": "💰",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["development-reform"]
        },
        "properties": {
            "frequency": "high",
            "priority": "medium"
        },
        "skills": ["data-analysis", "real-time-monitoring", "notification"],
        "welcome_message": "您好！我可以帮您：\n• 价格监测分析\n• 价格波动预警\n• 监测报告生成\n\n请告诉我监测商品和时间范围。",
        "tags": {
            "features": ["实时监测", "价格预警", "数据分析"],
            "keywords": ["价格", "监测", "预警"]
        }
    },
    
    # 城乡建设领域（3个）
    {
        "id": "construction-permit",
        "name": "施工许可",
        "description": "施工许可证办理辅助，支持施工许可申请、审核流程指导",
        "agent_id": "scene-construction-permit",
        "icon": "🏗️",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["housing-construction"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["document-analysis", "workflow", "compliance-check"],
        "welcome_message": "您好！我可以帮您：\n• 施工许可申请\n• 申请材料审核\n• 审批进度查询\n\n请告诉我项目信息和申请类型。",
        "tags": {
            "features": ["流程规范", "材料审核", "进度查询"],
            "keywords": ["施工许可", "办理", "审批"]
        }
    },
    {
        "id": "housing-security",
        "name": "住房保障",
        "description": "住房保障业务辅助，支持保障房申请、资格审核、分配管理",
        "agent_id": "scene-housing-security",
        "icon": "🏢",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["housing-construction"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["document-analysis", "workflow", "data-analysis"],
        "welcome_message": "您好！我可以帮您：\n• 保障房申请指导\n• 资格审核\n• 分配方案管理\n\n请告诉我申请类型和申请人信息。",
        "tags": {
            "features": ["资格审核", "分配管理", "流程规范"],
            "keywords": ["住房保障", "保障房", "申请"]
        }
    },
    {
        "id": "bidding-management",
        "name": "招投标管理",
        "description": "招投标业务辅助，支持招标文件审核、评标流程监督",
        "agent_id": "scene-bidding-management",
        "icon": "📋",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["housing-construction"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["document-analysis", "compliance-check"],
        "welcome_message": "您好！我可以帮您：\n• 招标文件审核\n• 评标流程监督\n• 异常情况识别\n\n请告诉我招标项目信息。",
        "tags": {
            "features": ["文件审核", "流程监督", "异常识别"],
            "keywords": ["招投标", "招标", "评标"]
        }
    },
    
    # 教育管理领域（4个）
    {
        "id": "enrollment-organization",
        "name": "招生组织",
        "description": "招生考试组织辅助，支持招生计划制定、考试组织协调",
        "agent_id": "scene-enrollment-organization",
        "icon": "📝",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["education"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "high"
        },
        "skills": ["document-analysis", "workflow", "data-analysis"],
        "welcome_message": "您好！我可以帮您：\n• 招生计划制定\n• 考试组织协调\n• 招生统计分析\n\n请告诉我招生类型和学校信息。",
        "tags": {
            "features": ["计划制定", "组织协调", "统计分析"],
            "keywords": ["招生", "考试", "录取"]
        }
    },
    {
        "id": "teacher-recruitment",
        "name": "教师招聘",
        "description": "教师招聘业务辅助，支持招聘计划、资格审核、面试组织",
        "agent_id": "scene-teacher-recruitment",
        "icon": "👨‍🏫",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["education"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "medium"
        },
        "skills": ["document-analysis", "workflow"],
        "welcome_message": "您好！我可以帮您：\n• 招聘计划制定\n• 资格审核\n• 面试组织\n\n请告诉我招聘类型和岗位信息。",
        "tags": {
            "features": ["计划制定", "资格审核", "面试组织"],
            "keywords": ["教师招聘", "招聘", "面试"]
        }
    },
    {
        "id": "teacher-training",
        "name": "教师培训",
        "description": "教师培训组织辅助，支持培训计划制定、培训效果评估",
        "agent_id": "scene-teacher-training",
        "icon": "📚",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["education"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "medium"
        },
        "skills": ["document-analysis", "knowledge-base"],
        "welcome_message": "您好！我可以帮您：\n• 培训计划制定\n• 培训资源组织\n• 培训效果评估\n\n请告诉我培训类型和对象。",
        "tags": {
            "features": ["计划制定", "资源组织", "效果评估"],
            "keywords": ["教师培训", "培训", "进修"]
        }
    },
    {
        "id": "education-quality-monitoring",
        "name": "质量监测",
        "description": "教育质量监测分析，支持教学质量评估、教育质量报告",
        "agent_id": "scene-education-quality-monitoring",
        "icon": "📊",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["education"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["data-analysis", "visualization", "report-generation"],
        "welcome_message": "您好！我可以帮您：\n• 教学质量评估\n• 质量监测分析\n• 质量报告生成\n\n请告诉我监测类型和学校信息。",
        "tags": {
            "features": ["质量评估", "数据分析", "报告生成"],
            "keywords": ["教育质量", "监测", "评估"]
        }
    },
    
    # 林草湿荒领域（3个）
    {
        "id": "logging-permit",
        "name": "采伐审批",
        "description": "林木采伐审批辅助，支持采伐许可申请、审核、监管",
        "agent_id": "scene-logging-permit",
        "icon": "🌲",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["forestry-grassland"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "medium"
        },
        "skills": ["document-analysis", "gis", "compliance-check"],
        "welcome_message": "您好！我可以帮您：\n• 采伐许可申请\n• 申请材料审核\n• 采伐监管\n\n请告诉我采伐类型和地点信息。",
        "tags": {
            "features": ["许可申请", "材料审核", "GIS监管"],
            "keywords": ["采伐", "许可", "林木"]
        }
    },
    {
        "id": "wildlife-protection",
        "name": "野生动物保护",
        "description": "野生动物保护辅助，支持野生动物监测、救助、保护管理",
        "agent_id": "scene-wildlife-protection",
        "icon": "🦌",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["forestry-grassland"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "medium"
        },
        "skills": ["gis", "image-analysis", "knowledge-base"],
        "welcome_message": "您好！我可以帮您：\n• 野生动物监测\n• 救助指导\n• 保护管理\n\n请告诉我保护类型和区域信息。",
        "tags": {
            "features": ["监测识别", "救助指导", "GIS支持"],
            "keywords": ["野生动物", "保护", "救助"]
        }
    },
    {
        "id": "wetland-protection",
        "name": "湿地保护",
        "description": "湿地保护管理辅助，支持湿地监测、生态修复、保护规划",
        "agent_id": "scene-wetland-protection",
        "icon": "🦆",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["forestry-grassland"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "medium"
        },
        "skills": ["gis", "image-analysis", "data-analysis"],
        "welcome_message": "您好！我可以帮您：\n• 湿地监测分析\n• 生态修复指导\n• 保护规划编制\n\n请告诉我湿地类型和保护需求。",
        "tags": {
            "features": ["监测分析", "生态修复", "GIS支持"],
            "keywords": ["湿地", "保护", "生态"]
        }
    },
    
    # 文化旅游领域（2个）
    {
        "id": "cultural-relics-protection",
        "name": "文物保护",
        "description": "文物保护管理辅助，支持文物巡查、保护规划、修缮管理",
        "agent_id": "scene-cultural-relics-protection",
        "icon": "🏛️",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["culture-tourism"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "high"
        },
        "skills": ["document-analysis", "image-analysis", "gis"],
        "welcome_message": "您好！我可以帮您：\n• 文物巡查管理\n• 保护规划编制\n• 修缮方案审核\n\n请告诉我文物类型和保护需求。",
        "tags": {
            "features": ["巡查管理", "保护规划", "修缮审核"],
            "keywords": ["文物", "保护", "修缮"]
        }
    },
    {
        "id": "intangible-heritage-protection",
        "name": "非遗保护",
        "description": "非物质文化遗产保护辅助，支持非遗项目申报、传承人管理",
        "agent_id": "scene-intangible-heritage-protection",
        "icon": "🎭",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["culture-tourism"]
        },
        "properties": {
            "frequency": "low",
            "priority": "medium"
        },
        "skills": ["document-analysis", "knowledge-base"],
        "welcome_message": "您好！我可以帮您：\n• 非遗项目申报\n• 传承人管理\n• 保护活动组织\n\n请告诉我非遗类型和保护需求。",
        "tags": {
            "features": ["项目申报", "传承人管理", "活动组织"],
            "keywords": ["非遗", "传承", "保护"]
        }
    },
    
    # 卫生健康领域（3个）
    {
        "id": "medical-institution-approval",
        "name": "医疗机构审批",
        "description": "医疗机构设置审批辅助，支持设置审批、执业登记、变更管理",
        "agent_id": "scene-medical-institution-approval",
        "icon": "🏥",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["health"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "high"
        },
        "skills": ["document-analysis", "compliance-check", "workflow"],
        "welcome_message": "您好！我可以帮您：\n• 设置审批申请\n• 执业登记\n• 变更管理\n\n请告诉我医疗机构类型和申请事项。",
        "tags": {
            "features": ["审批申请", "合规检查", "流程规范"],
            "keywords": ["医疗机构", "审批", "执业"]
        }
    },
    {
        "id": "disease-prevention",
        "name": "疾病预防",
        "description": "疾病预防控制辅助，支持疫情监测、预防接种、健康教育",
        "agent_id": "scene-disease-prevention",
        "icon": "💉",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["health"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["data-analysis", "real-time-monitoring", "notification"],
        "welcome_message": "您好！我可以帮您：\n• 疫情监测分析\n• 预防接种指导\n• 健康教育宣传\n\n请告诉我疾病类型和预防需求。",
        "tags": {
            "features": ["疫情监测", "预防接种", "健康教育"],
            "keywords": ["疾病预防", "疫情", "接种"]
        }
    },
    {
        "id": "health-promotion",
        "name": "健康促进",
        "description": "健康促进活动组织，支持健康教育、健康讲座、健康宣传",
        "agent_id": "scene-health-promotion",
        "icon": "❤️",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["health"]
        },
        "properties": {
            "frequency": "medium",
            "priority": "medium"
        },
        "skills": ["document-analysis", "knowledge-base"],
        "welcome_message": "您好！我可以帮您：\n• 健康教育活动\n• 健康讲座组织\n• 健康宣传策划\n\n请告诉我活动类型和目标人群。",
        "tags": {
            "features": ["活动组织", "讲座策划", "宣传设计"],
            "keywords": ["健康促进", "健康教育", "宣传"]
        }
    },
    
    # 综合执法领域（1个）
    {
        "id": "case-handling",
        "name": "案件办理",
        "description": "行政执法案件办理辅助，支持立案、调查、处罚、结案全流程",
        "agent_id": "scene-case-handling",
        "icon": "⚖️",
        "is_generic": False,
        "category": {
            "nature": None,
            "domains": ["comprehensive-enforcement"]
        },
        "properties": {
            "frequency": "high",
            "priority": "high"
        },
        "skills": ["document-analysis", "compliance-check", "workflow"],
        "welcome_message": "您好！我可以帮您：\n• 案件立案登记\n• 调查取证指导\n• 处罚决定审核\n• 结案归档\n\n请告诉我案件类型和基本情况。",
        "tags": {
            "features": ["立案登记", "调查取证", "处罚审核", "流程规范"],
            "keywords": ["案件", "执法", "处罚"]
        }
    }
]

def main():
    """主函数"""
    print("=" * 80)
    print("领域专属场景生成脚本")
    print("=" * 80)
    
    # 加载现有场景配置
    config_file = Path(__file__).parent / "scenes.json"
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    existing_scenes = config['scenes']
    
    print(f"\n现有场景数量：{len(existing_scenes)}")
    print(f"新增专属场景数量：{len(DOMAIN_SPECIFIC_SCENES)}")
    
    # 合并场景
    all_scenes = existing_scenes + DOMAIN_SPECIFIC_SCENES
    
    # 按领域统计
    print("\n按领域统计专属场景：")
    domain_count = {}
    for scene in DOMAIN_SPECIFIC_SCENES:
        for domain in scene['category']['domains']:
            domain_count[domain] = domain_count.get(domain, 0) + 1
    
    for domain, count in sorted(domain_count.items()):
        domain_names = {
            "natural-resources": "自然资源",
            "ecological-environment": "生态环境",
            "agriculture-rural": "农业农村",
            "development-reform": "发展改革",
            "housing-construction": "城乡建设",
            "education": "教育管理",
            "forestry-grassland": "林草湿荒",
            "culture-tourism": "文化旅游",
            "health": "卫生健康",
            "comprehensive-enforcement": "综合执法"
        }
        print(f"  {domain_names.get(domain, domain)}: {count} 个")
    
    # 更新配置
    config['scenes'] = all_scenes
    config['version'] = '3.0'
    config['updated_at'] = datetime.now().isoformat()
    
    # 保存配置
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 已更新配置文件：{config_file}")
    print(f"   总场景数：{len(all_scenes)}")
    print(f"   通用场景：{len([s for s in all_scenes if s['is_generic']])}")
    print(f"   专属场景：{len([s for s in all_scenes if not s['is_generic']])}")
    
    # 验证统计
    print("\n验证统计：")
    nature_total = sum(1 for s in all_scenes if s['category']['nature'])
    domain_total = sum(len(s['category']['domains']) for s in all_scenes)
    print(f"  通用分类总计：{nature_total} 个")
    print(f"  领域分类总计：{domain_total} 个")
    print(f"  实际场景总数：{len(all_scenes)} 个")

if __name__ == "__main__":
    main()
