from __future__ import annotations

from typing import Any

# 危机级高风险情绪词（触发最高优先级安全共情与 24 小时心理援助热线提示）
_CRISIS_KEYWORDS: tuple[str, ...] = (
    "不想活",
    "想自杀",
    "去自杀",
    "自杀念头",
    "轻生",
    "割腕",
    "跳楼",
    "跳河",
    "结束生命",
    "活着没意思",
    "活着好累想死",
    "我想死",
    "好想死",
    "自残",
    "伤害自己",
    "告别世界",
)

# 低谷级情绪困扰词（触发温柔情绪托底护栏与温和心理关怀卡片）
_DISTRESS_KEYWORDS: tuple[str, ...] = (
    "失恋",
    "刚分手",
    "被分手",
    "彻底分手",
    "好崩溃",
    "快崩溃",
    "崩溃了",
    "哭了一夜",
    "哭了一晚上",
    "整夜睡不着",
    "失眠好几天",
    "彻夜难眠",
    "被冷暴力",
    "心碎",
    "撑不住了",
    "太痛苦了",
    "我是不是很差劲",
    "觉得自己不配",
    "好绝望",
    "极度内耗",
)

REPLY_SCENES: tuple[dict[str, str], ...] = (
    {"code": "ambiguous", "label": "暧昧升温", "desc": "试探心意、自然拉近距离"},
    {"code": "cold_reply", "label": "对方冷淡", "desc": "回复敷衍、间隔变长怎么破局"},
    {"code": "conflict", "label": "吵架哄人", "desc": "情绪降温、体面化解僵局"},
    {"code": "date_invite", "label": "约会邀约", "desc": "发出或回应见面邀约"},
    {"code": "polite_decline", "label": "体面婉拒", "desc": "温和守边界、不伤和气"},
)

REPLY_TONES: tuple[dict[str, str], ...] = (
    {"code": "playful", "label": "俏皮拉扯", "desc": "轻幽默带点小反问，留出聊天钩子"},
    {"code": "gentle", "label": "温柔体贴", "desc": "先接住对方情绪，温暖有安全感"},
    {"code": "graceful", "label": "体面台阶", "desc": "不卑不亢，给彼此舒适退路"},
    {"code": "sincere", "label": "真诚直球", "desc": "坦荡清晰表达想法，减少猜忌内耗"},
    {"code": "humorous", "label": "幽默破冰", "desc": "轻松调侃化解尴尬或沉默"},
)

SOFTEN_INTENSITIES: tuple[dict[str, str], ...] = (
    {"code": "mild", "label": "有点委屈", "desc": "心里酸酸的，想温柔表达感受不被忽略"},
    {"code": "medium", "label": "明显生气", "desc": "有些火大或失望，想守住底线但不想翻脸"},
    {"code": "heated", "label": "快上头了", "desc": "差点把狠话/反话发出去，急需冷静降温"},
)

_SCENE_MAP = {item["code"]: item for item in REPLY_SCENES}
_TONE_MAP = {item["code"]: item for item in REPLY_TONES}
_INTENSITY_MAP = {item["code"]: item for item in SOFTEN_INTENSITIES}


def get_reply_helper_presets() -> dict[str, Any]:
    return {
        "scenes": list(REPLY_SCENES),
        "tones": list(REPLY_TONES),
    }


def get_soften_draft_presets() -> dict[str, Any]:
    return {
        "intensities": list(SOFTEN_INTENSITIES),
    }


def evaluate_emotion_care(text: str) -> dict[str, Any] | None:
    """毫秒级本地情绪关怀评估：返回 None 或含 prompt_guidance 与前端卡片数据的字典。"""
    normalized = (text or "").strip().lower()
    if not normalized:
        return None

    for kw in _CRISIS_KEYWORDS:
        if kw in normalized:
            return {
                "level": "crisis",
                "title": "你并不孤单，此刻请先保护好自己",
                "message": (
                    "我能感受到你正承受着非常沉重的情绪痛苦。请立刻联系身边信任的亲友陪伴，"
                    "或拨打下方 24 小时免费心理援助热线，专业倾听者会马上陪在你身边。"
                ),
                "hotlines": [
                    {"name": "全国 24 小时心理援助热线（希望 24）", "phone": "400-161-9995"},
                    {"name": "北京心理危机研究与干预中心", "phone": "010-82951332"},
                    {"name": "紧急救援 / 急救", "phone": "110 / 120"},
                ],
                "prompt_guidance": (
                    "[情绪安全护栏 — 最高优先级]\n"
                    "用户当前流露出强烈的绝望或自我伤害倾向。请务必：\n"
                    "1. 先以极度温和、真诚、不评判的语气接住对方此刻的痛苦，表达关心；\n"
                    "2. 明确、温柔地鼓励立刻联系身边的亲友，或拨打 24 小时心理援助热线"
                    "（400-161-9995 / 010-82951332），必要时拨打 110/120；\n"
                    "3. 严禁说教、指责、轻描淡写或提供任何危险信息。"
                ),
            }

    for kw in _DISTRESS_KEYWORDS:
        if kw in normalized:
            return {
                "level": "distress",
                "title": "情绪低谷温和陪伴提示",
                "message": (
                    "感情里的失落与消耗真的会让人非常疲惫。允许自己先慢下来、照顾好睡眠和情绪，"
                    "不必急着做决定；如果难受持续不散，也欢迎找信任的朋友或专业心理咨询师聊一聊。"
                ),
                "hotlines": [
                    {"name": "全国心理援助倾诉热线（24小时）", "phone": "400-161-9995"},
                ],
                "prompt_guidance": (
                    "[情绪托底护栏]\n"
                    "用户正处于失恋、冷战或明显情绪低谷中。请优先共情接纳与温和安抚，"
                    "避免居高临下说教或制造焦虑，再提供轻负担、可执行的自我照顾与稳妥沟通建议。"
                ),
            }

    return None


def strip_emotion_care_for_client(care: dict[str, Any] | None) -> dict[str, Any] | None:
    """移除内部 prompt_guidance，仅返回面向前端展示的关怀卡片数据。"""
    if not care:
        return None
    return {
        "level": care["level"],
        "title": care["title"],
        "message": care["message"],
        "hotlines": list(care.get("hotlines", [])),
    }


def build_reply_helper_prompt(
    *,
    partner_message: str,
    scene: str = "ambiguous",
    tone: str = "playful",
    context: str = "",
    my_intent: str = "",
    image_count: int = 0,
) -> tuple[str, str]:
    """构造「帮我回消息 / 聊天记录拆解（含截图识图）」结构化用户消息与专用输出格式要求。"""
    scene_info = _SCENE_MAP.get(scene, REPLY_SCENES[0])
    tone_info = _TONE_MAP.get(tone, REPLY_TONES[0])

    clean_partner = partner_message.strip()
    clean_ctx = context.strip()
    clean_intent = my_intent.strip()

    parts = [f"【帮我回消息 · {scene_info['label']} / {tone_info['label']}】"]
    if image_count > 0:
        parts.append(f"[已附 {image_count} 张微信聊天截图]")
    if clean_partner:
        parts.append(f"对方原话：\n「{clean_partner}」")
    elif image_count > 0:
        parts.append(
            "请先仔细识别我上传的微信聊天截图中的全部文字内容、左右双方发言顺序、"
            "消息时间间隔与表情/标点情绪，再替我剖析与拟定回复。"
        )
    if clean_ctx:
        parts.append(f"前文/背景补充：{clean_ctx}")
    if clean_intent:
        parts.append(f"我真实想表达的核心意思：{clean_intent}")
    parts.append(f"请帮我拆解潜台词，并按「{tone_info['label']}」语气给我 3 条可直接发送的高情商回复。")

    vision_rule = (
        "- 用户附带了微信聊天截图：请先看清左右气泡归属（右侧通常为用户本人，"
        "左侧通常为对方）、时间差、回复字数反差与表情包含义，再做判断。\n"
        if image_count > 0
        else ""
    )
    extra_instruction = (
        "[帮我回消息结构化拆解指令]\n"
        f"- 当前场景：{scene_info['label']}（{scene_info['desc']}）\n"
        f"- 目标语气：{tone_info['label']}（{tone_info['desc']}）\n"
        f"{vision_rule}"
        "- 请严格采用以下清晰的 Markdown 分节输出：\n"
        "  ### 🔍 潜台词与情绪拆解\n"
        "  简明点出对方字面之外的心理状态、试探意图或情绪温度（2~3 条要点）。\n"
        "  ### 💬 3 条可直接发送的备选回复\n"
        "  给出 3 条自然口语化、像真人发微信的回复（分别标注「稳妥版」「升温版」「轻巧留白版」），"
        "每条回复用引用块 `>` 单独一行写出来方便直接复制，并在下方用一句话说明发送效果。\n"
        "  ### ⚠️ 避坑提醒\n"
        "  指出此刻最容易踩坑的 1~2 种回复方式及原因。"
    )
    return "\n\n".join(parts), extra_instruction


def build_soften_draft_prompt(
    *,
    draft_message: str,
    context: str = "",
    intensity: str = "heated",
) -> tuple[str, str]:
    """构造「先别发！情绪降温与话术柔化器」结构化提问与三版本输出规范。"""
    level = _INTENSITY_MAP.get(intensity, SOFTEN_INTENSITIES[2])
    clean_draft = draft_message.strip()
    clean_ctx = context.strip()

    parts = [
        f"【先别发！话术柔化 · {level['label']}】",
        f"我差点发出去的原话草稿：\n「{clean_draft}」",
    ]
    if clean_ctx:
        parts.append(f"吵架/委屈前情背景：{clean_ctx}")
    parts.append(
        "请先帮我冷静踩下刹车，告诉我原话可能带来的误解，并改写成 3 个不委屈自己、又体面有效的版本。"
    )

    extra_instruction = (
        "[先别发 · 情绪降温与话术柔化指令]\n"
        f"- 当前情绪温度：{level['label']}（{level['desc']}）\n"
        "- 核心原则：绝不劝用户无底线忍让或压抑合理诉求，而是把「带刺的反话/攻击/指责」"
        "转化为「清晰表达感受 + 坚定且体面的边界 + 可沟通的出口」。\n"
        "- 请严格采用以下 Markdown 分节输出：\n"
        "  ### 🧊 先深呼吸：原话可能引发的误解\n"
        "  客观指出原话如果直接发出，对方第一反应会感受到什么防御或刺激，为什么可能把问题推远（2 条要点）。\n"
        "  ### 🌿 3 个更稳妥的替代版本\n"
        "  分别给出 3 个不同侧重的改写版本（标注「温柔表达委屈版」「不卑不亢立边界版」「轻俏皮给台阶版」），"
        "每条可直接发送的改写回复必须用引用块 `>` 单独一行写出（方便用户一键复制与收藏），"
        "再附一句话说明适用心态。\n"
        "  ### 💛 给此刻的你一句托底\n"
        "  用温暖、站在用户这边的 1~2 句话接住 TA 此刻的情绪。"
    )
    return "\n\n".join(parts), extra_instruction
