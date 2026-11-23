from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.db.redis import cache_delete, cache_get_json, cache_set_json
from app.models.sys_config import SysConfig

logger = logging.getLogger(__name__)

_SYS_CONFIG_CACHE_KEY = "ailove:sys:configs"

GROUP_LABELS: dict[str, str] = {
    "site": "站点与品牌",
    "security": "登录与会话安全",
    "registration": "注册与风控策略",
    "ai": "AI 对话策略",
    "log": "日志留存策略",
}


@dataclass(frozen=True)
class ConfigSpec:
    key: str
    group: str
    label: str
    value_type: str  # "string" | "int" | "float" | "bool" | "json"
    default: str
    description: str
    is_public: bool = False
    sort_order: int = 100
    min_val: float | None = None
    max_val: float | None = None


DEFAULT_CONFIG_SPECS: tuple[ConfigSpec, ...] = (
    # --- site ---
    ConfigSpec(
        key="site.name",
        group="site",
        label="平台品牌名称",
        value_type="string",
        default="AILOVE",
        description="显示在登录页、导航栏及浏览器标题栏的站点主名称",
        is_public=True,
        sort_order=10,
    ),
    ConfigSpec(
        key="site.subtitle",
        group="site",
        label="控制台副标题",
        value_type="string",
        default="管理与风控中台",
        description="展示在侧边栏品牌区与登录页的副标题说明",
        is_public=True,
        sort_order=20,
    ),
    ConfigSpec(
        key="site.announcement",
        group="site",
        label="全站系统公告",
        value_type="string",
        default="",
        description="非空时将在工作台顶部展示暖色通知横幅，留空则自动隐藏",
        is_public=True,
        sort_order=30,
    ),
    ConfigSpec(
        key="site.maintenance_mode",
        group="site",
        label="系统维护模式",
        value_type="bool",
        default="false",
        description="开启后仅允许管理端角色登录工作台，暂停普通用户新登录与自助注册",
        is_public=True,
        sort_order=40,
    ),
    # --- security ---
    ConfigSpec(
        key="security.session_ttl_hours",
        group="security",
        label="单次登录会话有效期（小时）",
        value_type="int",
        default="24",
        description="新签发 JWT 与 Redis 会话的硬性过期时长（范围 1 ~ 168 小时）",
        sort_order=10,
        min_val=1,
        max_val=168,
    ),
    ConfigSpec(
        key="security.max_sessions_per_user",
        group="security",
        label="单账号最多同时在线设备数",
        value_type="int",
        default="5",
        description="超出上限时按 FIFO 自动淘汰最早登录的终端（范围 1 ~ 20）",
        sort_order=20,
        min_val=1,
        max_val=20,
    ),
    ConfigSpec(
        key="security.login_max_fail_attempts",
        group="security",
        label="登录防爆破连续失败阈值",
        value_type="int",
        default="5",
        description="同一账号连续密码错误达到该次数后自动触发临时锁定（范围 3 ~ 20）",
        sort_order=30,
        min_val=3,
        max_val=20,
    ),
    ConfigSpec(
        key="security.login_lock_minutes",
        group="security",
        label="防爆破触发锁定时长（分钟）",
        value_type="int",
        default="15",
        description="达到失败阈值后暂停该账号登录的冷却时长（范围 1 ~ 120 分钟）",
        sort_order=40,
        min_val=1,
        max_val=120,
    ),
    ConfigSpec(
        key="security.password_min_length",
        group="security",
        label="密码最短长度要求",
        value_type="int",
        default="8",
        description="注册、分配创建及修改密码时校验的最小字符数（范围 6 ~ 32，且须含字母和数字）",
        sort_order=50,
        min_val=6,
        max_val=32,
    ),
    # --- registration ---
    ConfigSpec(
        key="registration.enabled",
        group="registration",
        label="开放邮箱自助注册",
        value_type="bool",
        default="true",
        description="关闭后登录页自动隐藏「注册账号」页签且后端拒绝自助注册请求",
        is_public=True,
        sort_order=10,
    ),
    ConfigSpec(
        key="registration.strict_email_policy",
        group="registration",
        label="严格拦截域名/非主流邮箱",
        value_type="bool",
        default="true",
        description="开启时执行六层邮箱风控引擎，仅放行正规主流公共邮箱自助注册",
        sort_order=20,
    ),
    ConfigSpec(
        key="registration.slider_captcha_enabled",
        group="registration",
        label="启用弹窗拼图滑动验证",
        value_type="bool",
        default="true",
        description="控制注册/登录前是否弹出防机器人拼图滑块与 7 维轨迹校验",
        is_public=True,
        sort_order=30,
    ),
    # --- ai ---
    ConfigSpec(
        key="ai.inject_realtime_clock",
        group="ai",
        label="自动注入实时系统时钟上下文",
        value_type="bool",
        default="true",
        description="每轮对话前向 System Prompt 注入实时精确日期、星期与时间，避免模型无法回答今日日期",
        sort_order=10,
    ),
    ConfigSpec(
        key="ai.default_timezone",
        group="ai",
        label="AI 对话默认时区",
        value_type="string",
        default="Asia/Shanghai",
        description="客户端未传递时区时使用的 IANA 标准时区（如 Asia/Shanghai）",
        sort_order=20,
    ),
    ConfigSpec(
        key="ai.max_message_length",
        group="ai",
        label="单条提问最大字符数",
        value_type="int",
        default="4000",
        description="限制单次用户输入 Prompt 的最大字符长度（范围 200 ~ 8000）",
        sort_order=30,
        min_val=200,
        max_val=8000,
    ),
    # --- log ---
    ConfigSpec(
        key="log.audit_enabled",
        group="log",
        label="开启操作审计日志采集",
        value_type="bool",
        default="true",
        description="开启后自动记录所有写入操作与 403/5xx 安全事件至审计中心",
        sort_order=10,
    ),
    ConfigSpec(
        key="log.retention_days",
        group="log",
        label="审计与登录日志保留天数",
        value_type="int",
        default="90",
        description="手动一键清理过期日志时默认保留的最近天数（范围 7 ~ 365 天）",
        sort_order=20,
        min_val=7,
        max_val=365,
    ),
)

_SPEC_MAP: dict[str, ConfigSpec] = {s.key: s for s in DEFAULT_CONFIG_SPECS}
_mem_sys_configs: dict[str, dict[str, Any]] = {}


def _ensure_mem_seed() -> None:
    if not _mem_sys_configs:
        now = datetime.now(UTC).replace(tzinfo=None)
        for spec in DEFAULT_CONFIG_SPECS:
            _mem_sys_configs[spec.key] = {
                "config_key": spec.key,
                "group_name": spec.group,
                "label": spec.label,
                "value_type": spec.value_type,
                "config_value": spec.default,
                "default_value": spec.default,
                "description": spec.description,
                "is_public": spec.is_public,
                "is_secret": False,
                "sort_order": spec.sort_order,
                "updated_at": now,
            }


def _parse_typed_value(raw_val: Any, value_type: str) -> Any:
    if value_type == "bool":
        if isinstance(raw_val, bool):
            return raw_val
        return str(raw_val).strip().lower() in {"1", "true", "yes", "on"}
    if value_type == "int":
        try:
            return int(float(raw_val))
        except (TypeError, ValueError):
            return 0
    if value_type == "float":
        try:
            return float(raw_val)
        except (TypeError, ValueError):
            return 0.0
    if value_type == "json":
        if isinstance(raw_val, (dict, list)):
            return raw_val
        try:
            return json.loads(str(raw_val or "{}"))
        except ValueError:
            return {}
    return "" if raw_val is None else str(raw_val)


def _serialize_and_validate(spec: ConfigSpec, new_value: Any) -> str:
    if spec.value_type == "bool":
        if isinstance(new_value, bool):
            return "true" if new_value else "false"
        s = str(new_value).strip().lower()
        if s in {"true", "1", "yes", "on"}:
            return "true"
        if s in {"false", "0", "no", "off"}:
            return "false"
        raise BusinessException(f"配置项「{spec.label}」须为布尔值", code=40071)

    if spec.value_type == "int":
        try:
            num = int(new_value) if not isinstance(new_value, bool) else -999999
        except (TypeError, ValueError) as exc:
            raise BusinessException(f"配置项「{spec.label}」须为整数", code=40071) from exc
        if isinstance(new_value, bool):
            raise BusinessException(f"配置项「{spec.label}」须为整数", code=40071)
        if spec.min_val is not None and num < spec.min_val:
            raise BusinessException(
                f"配置项「{spec.label}」不能小于 {int(spec.min_val)}", code=40072
            )
        if spec.max_val is not None and num > spec.max_val:
            raise BusinessException(
                f"配置项「{spec.label}」不能大于 {int(spec.max_val)}", code=40072
            )
        return str(num)

    if spec.value_type == "float":
        try:
            fnum = float(new_value)
        except (TypeError, ValueError) as exc:
            raise BusinessException(f"配置项「{spec.label}」须为数值", code=40071) from exc
        if spec.min_val is not None and fnum < spec.min_val:
            raise BusinessException(f"配置项「{spec.label}」不能小于 {spec.min_val}", code=40072)
        if spec.max_val is not None and fnum > spec.max_val:
            raise BusinessException(f"配置项「{spec.label}」不能大于 {spec.max_val}", code=40072)
        return str(fnum)

    text = "" if new_value is None else str(new_value).strip()
    if len(text) > 1000:
        raise BusinessException(f"配置项「{spec.label}」内容过长（最多 1000 字符）", code=40073)
    return text


async def invalidate_sys_config_cache() -> None:
    await cache_delete(_SYS_CONFIG_CACHE_KEY)


async def ensure_default_sys_configs() -> None:
    """启动时幂等补全系统配置项（仅插入缺失键，不覆盖管理员已调整的线上值）。"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            existing_keys = set(
                (await session.execute(select(SysConfig.config_key))).scalars().all()
            )
            added = 0
            for spec in DEFAULT_CONFIG_SPECS:
                if spec.key not in existing_keys:
                    session.add(
                        SysConfig(
                            config_key=spec.key,
                            group_name=spec.group,
                            label=spec.label,
                            value_type=spec.value_type,
                            config_value=spec.default,
                            default_value=spec.default,
                            description=spec.description,
                            is_public=spec.is_public,
                            is_secret=False,
                            sort_order=spec.sort_order,
                        )
                    )
                    added += 1
            if added:
                await session.commit()
                await invalidate_sys_config_cache()
                logger.info("Initialized %d default sys_configs items.", added)
    except IntegrityError:
        logger.info("Default sys_configs already initialized by another worker.")
    except Exception as exc:
        logger.warning("Skip default sys_configs bootstrap: %s", exc)


async def get_config_map() -> dict[str, Any]:
    """获取全部配置键 -> 强类型值映射（优先 Redis 热缓存）。"""
    cached = await cache_get_json(_SYS_CONFIG_CACHE_KEY)
    if isinstance(cached, dict) and "site.name" in cached:
        return cached

    raw_map: dict[str, tuple[str, str]] = {}
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (await session.execute(select(SysConfig))).scalars().all()
            if rows:
                for r in rows:
                    raw_map[r.config_key] = (r.config_value, r.value_type)
    except (SQLAlchemyError, OSError):
        pass

    if not raw_map:
        _ensure_mem_seed()
        for k, rec in _mem_sys_configs.items():
            raw_map[k] = (rec["config_value"], rec["value_type"])

    parsed: dict[str, Any] = {}
    for spec in DEFAULT_CONFIG_SPECS:
        raw_val, vtype = raw_map.get(spec.key, (spec.default, spec.value_type))
        parsed[spec.key] = _parse_typed_value(raw_val, vtype)
    for k, (raw_val, vtype) in raw_map.items():
        if k not in parsed:
            parsed[k] = _parse_typed_value(raw_val, vtype)

    await cache_set_json(_SYS_CONFIG_CACHE_KEY, parsed, ttl_seconds=300)
    return parsed


async def get_bool(key: str, default: bool = False) -> bool:
    cfg = await get_config_map()
    if key not in cfg:
        return default
    return bool(cfg[key])


async def get_int(key: str, default: int = 0) -> int:
    cfg = await get_config_map()
    if key not in cfg:
        return default
    try:
        return int(cfg[key])
    except (TypeError, ValueError):
        return default


async def get_str(key: str, default: str = "") -> str:
    cfg = await get_config_map()
    val = cfg.get(key)
    return default if val is None else str(val)


async def get_public_configs() -> dict[str, Any]:
    """返回登录页与公开端所需的非敏感运行时配置。"""
    cfg = await get_config_map()
    public_items = {
        spec.key: cfg.get(spec.key, _parse_typed_value(spec.default, spec.value_type))
        for spec in DEFAULT_CONFIG_SPECS
        if spec.is_public
    }
    return {
        "site_name": str(public_items.get("site.name", "AILOVE")),
        "site_subtitle": str(public_items.get("site.subtitle", "管理与风控中台")),
        "announcement": str(public_items.get("site.announcement", "")),
        "maintenance_mode": bool(public_items.get("site.maintenance_mode", False)),
        "registration_enabled": bool(public_items.get("registration.enabled", True)),
        "slider_captcha_enabled": bool(public_items.get("registration.slider_captcha_enabled", True)),
        "configs": public_items,
    }


def _build_item_dict(
    *,
    key: str,
    group_name: str,
    label: str,
    value_type: str,
    raw_value: str,
    default_value: str,
    description: str,
    is_public: bool,
    updated_at: datetime | None,
) -> dict[str, Any]:
    spec = _SPEC_MAP.get(key)
    return {
        "config_key": key,
        "group_name": group_name,
        "label": label,
        "value_type": value_type,
        "value": _parse_typed_value(raw_value, value_type),
        "default_value": _parse_typed_value(default_value, value_type),
        "description": description,
        "is_public": is_public,
        "min_val": spec.min_val if spec else None,
        "max_val": spec.max_val if spec else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


async def list_grouped_configs() -> dict[str, Any]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(SysConfig).order_by(SysConfig.group_name.asc(), SysConfig.sort_order.asc())
                )
            ).scalars().all()
            for r in rows:
                rows_by_key[r.config_key] = _build_item_dict(
                    key=r.config_key,
                    group_name=r.group_name,
                    label=r.label,
                    value_type=r.value_type,
                    raw_value=r.config_value,
                    default_value=r.default_value,
                    description=r.description,
                    is_public=r.is_public,
                    updated_at=r.updated_at,
                )
    except (SQLAlchemyError, OSError):
        pass

    if not rows_by_key:
        _ensure_mem_seed()
        for k, rec in _mem_sys_configs.items():
            rows_by_key[k] = _build_item_dict(
                key=k,
                group_name=rec["group_name"],
                label=rec["label"],
                value_type=rec["value_type"],
                raw_value=rec["config_value"],
                default_value=rec["default_value"],
                description=rec["description"],
                is_public=rec["is_public"],
                updated_at=rec.get("updated_at"),
            )

    grouped: list[dict[str, Any]] = []
    for g_key, g_label in GROUP_LABELS.items():
        items = [
            rows_by_key[s.key]
            for s in DEFAULT_CONFIG_SPECS
            if s.group == g_key and s.key in rows_by_key
        ]
        grouped.append({"group": g_key, "label": g_label, "items": items})

    return {"groups": grouped}


async def batch_update_configs(updates: dict[str, Any], admin_id: int) -> dict[str, Any]:
    validated: dict[str, str] = {}
    for k, val in updates.items():
        spec = _SPEC_MAP.get(k)
        if spec is None:
            raise BusinessException(f"未知的系统配置项：{k}", code=40070)
        validated[k] = _serialize_and_validate(spec, val)

    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(SysConfig).where(SysConfig.config_key.in_(list(validated.keys())))
                )
            ).scalars().all()
            existing_map = {r.config_key: r for r in rows}
            for k, str_val in validated.items():
                row = existing_map.get(k)
                if row is not None:
                    row.config_value = str_val
                    row.updated_by = admin_id
                else:
                    spec = _SPEC_MAP[k]
                    session.add(
                        SysConfig(
                            config_key=spec.key,
                            group_name=spec.group,
                            label=spec.label,
                            value_type=spec.value_type,
                            config_value=str_val,
                            default_value=spec.default,
                            description=spec.description,
                            is_public=spec.is_public,
                            is_secret=False,
                            sort_order=spec.sort_order,
                            updated_by=admin_id,
                        )
                    )
            await session.commit()
    except (SQLAlchemyError, OSError):
        _ensure_mem_seed()
        now = datetime.now(UTC).replace(tzinfo=None)
        for k, str_val in validated.items():
            if k in _mem_sys_configs:
                _mem_sys_configs[k]["config_value"] = str_val
                _mem_sys_configs[k]["updated_at"] = now

    await invalidate_sys_config_cache()
    return await list_grouped_configs()


async def reset_configs(group_name: str | None, admin_id: int) -> dict[str, Any]:
    if group_name and group_name not in GROUP_LABELS:
        raise BusinessException(f"未知的配置分组：{group_name}", code=40074)

    target_specs = [
        s for s in DEFAULT_CONFIG_SPECS if group_name is None or s.group == group_name
    ]
    target_keys = [s.key for s in target_specs]

    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(select(SysConfig).where(SysConfig.config_key.in_(target_keys)))
            ).scalars().all()
            for r in rows:
                r.config_value = r.default_value
                r.updated_by = admin_id
            await session.commit()
    except (SQLAlchemyError, OSError):
        _ensure_mem_seed()
        now = datetime.now(UTC).replace(tzinfo=None)
        for k in target_keys:
            if k in _mem_sys_configs:
                _mem_sys_configs[k]["config_value"] = _mem_sys_configs[k]["default_value"]
                _mem_sys_configs[k]["updated_at"] = now

    await invalidate_sys_config_cache()
    return await list_grouped_configs()
