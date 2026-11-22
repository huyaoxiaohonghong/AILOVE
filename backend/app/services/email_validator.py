from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

import dns.asyncresolver
import dns.exception

from app.db.redis import cache_get_json, cache_set_json

logger = logging.getLogger(__name__)

# 严格 ASCII 邮箱语法校验（拒绝非 ASCII / 国际化同形字混淆）
_LOCAL_RE = re.compile(r"^[a-z0-9._+-]{1,64}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    region: str
    canonical_domain: str | None = None
    ignore_dots: bool = False
    mx_keywords: tuple[str, ...] = ()


# 主流正规个人公共邮箱服务商注册表
MAINSTREAM_PROVIDERS: dict[str, ProviderSpec] = {
    # 国内主流公共邮箱
    "qq.com": ProviderSpec("QQ邮箱", "CN", mx_keywords=("qq.com",)),
    "foxmail.com": ProviderSpec("Foxmail邮箱", "CN", mx_keywords=("qq.com",)),
    "vip.qq.com": ProviderSpec("QQ VIP邮箱", "CN", mx_keywords=("qq.com",)),
    "163.com": ProviderSpec("网易163邮箱", "CN", mx_keywords=("163.com", "netease.com")),
    "126.com": ProviderSpec("网易126邮箱", "CN", mx_keywords=("126.com", "163.com", "netease.com")),
    "yeah.net": ProviderSpec("网易Yeah邮箱", "CN", mx_keywords=("yeah.net", "163.com", "netease.com")),
    "vip.163.com": ProviderSpec("网易VIP 163邮箱", "CN", mx_keywords=("163.com", "netease.com")),
    "vip.126.com": ProviderSpec("网易VIP 126邮箱", "CN", mx_keywords=("126.com", "163.com")),
    "sina.com": ProviderSpec("新浪邮箱", "CN", mx_keywords=("sina.com",)),
    "sina.cn": ProviderSpec("新浪CN邮箱", "CN", mx_keywords=("sina.cn", "sina.com")),
    "vip.sina.com": ProviderSpec("新浪VIP邮箱", "CN", mx_keywords=("sina.com",)),
    "sohu.com": ProviderSpec("搜狐邮箱", "CN", mx_keywords=("sohu.com",)),
    "aliyun.com": ProviderSpec("阿里云个人邮箱", "CN", mx_keywords=("aliyun.com", "mxhichina.com")),
    "139.com": ProviderSpec("中国移动139邮箱", "CN", mx_keywords=("139.com", "10086.cn")),
    "189.cn": ProviderSpec("中国电信189邮箱", "CN", mx_keywords=("189.cn",)),
    "wo.cn": ProviderSpec("中国联通沃邮箱", "CN", mx_keywords=("wo.cn",)),
    "tom.com": ProviderSpec("TOM邮箱", "CN", mx_keywords=("tom.com",)),
    "21cn.com": ProviderSpec("21CN邮箱", "CN", mx_keywords=("21cn.com",)),
    # 国际主流公共邮箱
    "gmail.com": ProviderSpec(
        "Gmail", "GLOBAL", canonical_domain="gmail.com", ignore_dots=True, mx_keywords=("google.com",)
    ),
    "googlemail.com": ProviderSpec(
        "Gmail", "GLOBAL", canonical_domain="gmail.com", ignore_dots=True, mx_keywords=("google.com",)
    ),
    "outlook.com": ProviderSpec("Outlook", "GLOBAL", mx_keywords=("outlook.com", "hotmail.com")),
    "hotmail.com": ProviderSpec("Hotmail", "GLOBAL", mx_keywords=("outlook.com", "hotmail.com")),
    "live.com": ProviderSpec("Microsoft Live", "GLOBAL", mx_keywords=("outlook.com", "hotmail.com")),
    "msn.com": ProviderSpec("MSN邮箱", "GLOBAL", mx_keywords=("outlook.com", "hotmail.com")),
    "icloud.com": ProviderSpec("Apple iCloud", "GLOBAL", mx_keywords=("icloud.com", "apple.com")),
    "me.com": ProviderSpec("Apple iCloud", "GLOBAL", mx_keywords=("icloud.com", "apple.com")),
    "mac.com": ProviderSpec("Apple iCloud", "GLOBAL", mx_keywords=("icloud.com", "apple.com")),
    "yahoo.com": ProviderSpec("Yahoo邮箱", "GLOBAL", mx_keywords=("yahoodns.net", "yahoo.com")),
    "yahoo.co.jp": ProviderSpec("Yahoo Japan", "GLOBAL", mx_keywords=("yahoo.co.jp",)),
    "proton.me": ProviderSpec("Proton Mail", "GLOBAL", mx_keywords=("protonmail.ch", "proton.me")),
    "protonmail.com": ProviderSpec("Proton Mail", "GLOBAL", mx_keywords=("protonmail.ch",)),
    "aol.com": ProviderSpec("AOL Mail", "GLOBAL", mx_keywords=("yahoodns.net", "aol.com")),
    "zoho.com": ProviderSpec("Zoho Mail", "GLOBAL", mx_keywords=("zoho.com",)),
    "yandex.com": ProviderSpec("Yandex Mail", "GLOBAL", mx_keywords=("yandex.ru", "yandex.net")),
    "gmx.com": ProviderSpec("GMX Mail", "GLOBAL", mx_keywords=("gmx.net", "gmx.com")),
    "mail.com": ProviderSpec("Mail.com", "GLOBAL", mx_keywords=("mail.com",)),
}

# 常见一次性 / 临时 / 匿名转发邮箱域名库
DISPOSABLE_DOMAINS: frozenset[str] = frozenset(
    {
        "mailinator.com",
        "10minutemail.com",
        "10minutemail.net",
        "guerrillamail.com",
        "guerrillamail.org",
        "guerrillamail.net",
        "sharklasers.com",
        "grr.la",
        "tempmail.com",
        "temp-mail.org",
        "temp-mail.io",
        "tempmail.plus",
        "tmpmail.org",
        "tmpmail.net",
        "yopmail.com",
        "yopmail.fr",
        "yopmail.net",
        "trashmail.com",
        "trashmail.net",
        "maildrop.cc",
        "moakt.com",
        "moakt.cc",
        "dispostable.com",
        "getnada.com",
        "nada.email",
        "linshiyouxiang.net",
        "linshi-email.com",
        "bccto.me",
        "chacuo.net",
        "snapmail.cc",
        "emailondeck.com",
        "mohmal.com",
        "mailnesia.com",
        "fakeinbox.com",
        "throwawaymail.com",
        "tempail.com",
        "mintemail.com",
        "mailcatch.com",
        "getairmail.com",
        "mytemp.email",
        "burnermail.io",
        "duck.com",
        "simplelogin.com",
        "simplelogin.co",
        "anonaddy.com",
        "addy.io",
        "mozmail.com",
        "relay.firefox.com",
        "33mail.com",
    }
)

DISPOSABLE_KEYWORDS: tuple[str, ...] = (
    "tempmail",
    "temp-mail",
    "tmpmail",
    "trashmail",
    "10minute",
    "guerrilla",
    "throwaway",
    "disposable",
    "mailinator",
    "linshi",
    "burner",
    "fakeinbox",
    "spambox",
    "yopmail",
    "dropmail",
)

# 非主流个人消费邮箱常见的高危廉价自定义域名后缀
HIGH_RISK_TLDS: frozenset[str] = frozenset(
    {
        "xyz",
        "top",
        "club",
        "icu",
        "vip",
        "shop",
        "site",
        "online",
        "tk",
        "ml",
        "ga",
        "cf",
        "gq",
        "buzz",
        "click",
        "work",
        "fun",
        "store",
        "monster",
        "cyou",
        "cfd",
        "sbs",
        "pw",
        "cc",
        "loan",
        "bid",
    }
)

# 禁止普通用户自助注册的系统角色前缀
RESERVED_LOCAL_PREFIXES: frozenset[str] = frozenset(
    {
        "admin",
        "administrator",
        "root",
        "postmaster",
        "webmaster",
        "hostmaster",
        "abuse",
        "noreply",
        "no-reply",
        "mailer-daemon",
        "support",
        "security",
        "system",
        "billing",
    }
)

# 企业自定义域名邮箱 / 邮件转发托管商 MX 指纹
ENTERPRISE_MX_FINGERPRINTS: tuple[tuple[str, str], ...] = (
    ("exmail.qq.com", "腾讯企业域名邮箱"),
    ("mxbiz1.qq.com", "腾讯企业域名邮箱"),
    ("mxbiz2.qq.com", "腾讯企业域名邮箱"),
    ("mxhichina.com", "阿里企业域名邮箱"),
    ("qiye.aliyun.com", "阿里企业域名邮箱"),
    ("qiye.163.com", "网易企业域名邮箱"),
    ("ym.163.com", "网易免费企业域名邮箱"),
    ("feishu.cn", "飞书企业域名邮箱"),
    ("larksuite.com", "Lark/飞书企业域名邮箱"),
    ("google.com", "Google Workspace 自定义域名邮箱"),
    ("googlemail.com", "Google Workspace 自定义域名邮箱"),
    ("protection.outlook.com", "Microsoft 365 自定义域名邮箱"),
    ("zoho.com", "Zoho 自定义域名邮箱"),
    ("zoho.eu", "Zoho 自定义域名邮箱"),
    ("cloudflare.net", "Cloudflare 域名邮件转发"),
    ("improvmx.com", "ImprovMX 域名邮件转发"),
    ("forwardemail.net", "ForwardEmail 域名邮件转发"),
    ("mailgun.org", "Mailgun 域名邮件服务"),
    ("amazonses.com", "AWS SES 域名邮件服务"),
    ("sendgrid.net", "SendGrid 域名邮件服务"),
    ("fastmail.com", "Fastmail 自定义域名邮箱"),
    ("migadu.com", "Migadu 自定义域名邮箱"),
)


@dataclass
class EmailAnalysisResult:
    email: str
    canonical_email: str
    allowed: bool
    trust_score: int
    category: str
    provider: str
    mx_hosts: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "canonical_email": self.canonical_email,
            "allowed": self.allowed,
            "trust_score": self.trust_score,
            "category": self.category,
            "provider": self.provider,
            "mx_hosts": self.mx_hosts,
            "reasons": self.reasons,
            "summary": self.summary,
        }


def damerau_levenshtein(a: str, b: str) -> int:
    """计算 Damerau-Levenshtein 编辑距离（支持相邻字符交换，用于识别仿冒主流邮箱域名）。"""
    la, lb = len(a), len(b)
    if abs(la - lb) > 2:
        return 3
    dp = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        dp[i][0] = i
    for j in range(lb + 1):
        dp[0][j] = j

    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + cost,
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                dp[i][j] = min(dp[i][j], dp[i - 2][j - 2] + 1)
    return dp[la][lb]


def shannon_entropy(text: str) -> float:
    """计算字符串香农信息熵（bits/char），用于检测机器随机生成的邮箱前缀。"""
    if not text:
        return 0.0
    freq: dict[str, int] = {}
    for ch in text:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def char_transition_rate(text: str) -> float:
    """计算字母与数字/符号之间的高频交替切换率，识别随机脚本前缀。"""
    if len(text) < 2:
        return 0.0

    def _cls(ch: str) -> int:
        if ch.isdigit():
            return 1
        if ch.isalpha():
            return 2
        return 3

    switches = sum(1 for i in range(1, len(text)) if _cls(text[i]) != _cls(text[i - 1]))
    return switches / (len(text) - 1)


class EmailTrustAnalyzer:
    """六层非正规/域名邮箱识别与可信度评估引擎。"""

    def __init__(self, dns_timeout: float = 2.0) -> None:
        self.dns_timeout = dns_timeout

    async def lookup_mx_hosts(self, domain: str) -> tuple[list[str], bool]:
        """异步探测域名 MX 记录并缓存至 Redis，返回 (mx_hosts, dns_checked)。"""
        cache_key = f"ailove:dns:mx:{domain}"
        cached = await cache_get_json(cache_key)
        if isinstance(cached, dict) and "hosts" in cached:
            return list(cached["hosts"]), bool(cached.get("checked", True))

        resolver = dns.asyncresolver.Resolver()
        resolver.lifetime = self.dns_timeout
        resolver.timeout = self.dns_timeout

        try:
            answers = await resolver.resolve(domain, "MX")
            hosts = sorted(
                {str(rdata.exchange).rstrip(".").lower() for rdata in answers if rdata.exchange}
            )
            await cache_set_json(cache_key, {"hosts": hosts, "checked": True}, ttl_seconds=21600)
            return hosts, True
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            await cache_set_json(cache_key, {"hosts": [], "checked": True}, ttl_seconds=3600)
            return [], True
        except (dns.exception.DNSException, OSError) as exc:
            logger.debug("DNS MX lookup skipped for %s: %s", domain, exc)
            return [], False

    def _fingerprint_enterprise_mx(self, mx_hosts: list[str]) -> str | None:
        for host in mx_hosts:
            for suffix, label in ENTERPRISE_MX_FINGERPRINTS:
                if host == suffix or host.endswith(f".{suffix}"):
                    return label
        return None

    def _find_typosquatting_target(self, domain: str) -> str | None:
        if len(domain) < 5:
            return None
        for official in MAINSTREAM_PROVIDERS:
            if domain == official:
                return None
            if damerau_levenshtein(domain, official) == 1:
                return official
        return None

    def _canonicalize(self, local: str, domain: str, spec: ProviderSpec | None) -> str:
        clean_local = local.split("+", 1)[0]
        target_domain = domain
        if spec is not None:
            if spec.ignore_dots:
                clean_local = clean_local.replace(".", "")
            if spec.canonical_domain:
                target_domain = spec.canonical_domain
        return f"{clean_local}@{target_domain}"

    async def analyze(
        self,
        raw_email: str,
        *,
        check_mx: bool = True,
        strict_registration: bool = True,
    ) -> EmailAnalysisResult:
        """
        对邮箱执行六层识别分析：
        1. 语法、ASCII 与 Punycode 同形字防御
        2. 一次性/临时邮箱与高危 TLD 拦截
        3. 主流公共邮箱注册表 + 子域伪造 + 编辑距离仿冒检测
        4. 异步 DNS MX 探测与企业自定义域名邮箱指纹识别
        5. 前缀归一化（防 +别名/Gmail 点号绕过）、QQ号段、信息熵与切换率反批量检测
        6. 综合评分（0-100）与可解释决策输出
        """
        email = (raw_email or "").strip().lower()
        reasons: list[str] = []

        # Layer 1: 基础格式与同形字混淆校验
        if not email or len(email) > 254 or email.count("@") != 1:
            return EmailAnalysisResult(
                email=email,
                canonical_email=email,
                allowed=False,
                trust_score=0,
                category="invalid_syntax",
                provider="未知",
                reasons=["邮箱格式不正确"],
                summary="请输入有效的邮箱地址",
            )

        if not email.isascii():
            return EmailAnalysisResult(
                email=email,
                canonical_email=email,
                allowed=False,
                trust_score=0,
                category="homograph_attack",
                provider="非法域名",
                reasons=["检测到非 ASCII 字符，拦截潜在同形字欺骗邮箱"],
                summary="邮箱包含非法字符，不支持注册",
            )

        local, domain = email.split("@", 1)
        if (
            not _LOCAL_RE.match(local)
            or not _DOMAIN_RE.match(domain)
            or local.startswith(".")
            or local.endswith(".")
            or ".." in local
        ):
            return EmailAnalysisResult(
                email=email,
                canonical_email=email,
                allowed=False,
                trust_score=0,
                category="invalid_syntax",
                provider="未知",
                reasons=["邮箱用户名或域名不符合 RFC 规范"],
                summary="邮箱格式不符合规范",
            )

        if "xn--" in domain:
            return EmailAnalysisResult(
                email=email,
                canonical_email=email,
                allowed=False,
                trust_score=5,
                category="homograph_attack",
                provider="Punycode域名",
                reasons=["检测到 Punycode (xn--) 国际化域名，存在同形字仿冒风险"],
                summary="不允许使用国际化编码域名邮箱注册",
            )

        # Layer 2: 一次性 / 临时 / 匿名转发邮箱识别
        if domain in DISPOSABLE_DOMAINS or any(kw in domain for kw in DISPOSABLE_KEYWORDS):
            return EmailAnalysisResult(
                email=email,
                canonical_email=email,
                allowed=False,
                trust_score=5,
                category="disposable",
                provider="临时/转发邮箱",
                reasons=[f"域名 {domain} 命中一次性临时邮箱或匿名转发服务特征库"],
                summary="不允许使用临时邮箱或匿名转发邮箱注册",
            )

        # Layer 3: 主流正规公共邮箱判定 + 子域伪造 + Damerau-Levenshtein 仿冒检测
        spec = MAINSTREAM_PROVIDERS.get(domain)
        canonical = self._canonicalize(local, domain, spec)

        if spec is None:
            # 检测是否冒充主流邮箱子域名（如 user@mail.qq.com）
            for official in MAINSTREAM_PROVIDERS:
                if domain.endswith(f".{official}"):
                    return EmailAnalysisResult(
                        email=email,
                        canonical_email=canonical,
                        allowed=False,
                        trust_score=10,
                        category="subdomain_spoofing",
                        provider="伪造子域邮箱",
                        reasons=[f"域名 {domain} 为 {official} 的非正规子域形式"],
                        summary="不允许使用非主流子域名邮箱注册，请使用正规公共邮箱",
                    )

            # 检测仿冒主流邮箱域名（编辑距离=1）
            typo_target = self._find_typosquatting_target(domain)
            if typo_target:
                return EmailAnalysisResult(
                    email=email,
                    canonical_email=canonical,
                    allowed=False,
                    trust_score=10,
                    category="typosquatting",
                    provider="疑似仿冒域名",
                    reasons=[f"域名 {domain} 与正规邮箱 {typo_target} 编辑距离为 1，疑似拼写错误或仿冒域名"],
                    summary=f"邮箱域名疑似拼写错误或仿冒（您是否想输入 @{typo_target}？）",
                )

            tld = domain.rsplit(".", 1)[-1]
            if tld in HIGH_RISK_TLDS:
                reasons.append(f"域名后缀 .{tld} 属于高风险非常规个人邮箱后缀")

            # Layer 4: 对非常规域名执行异步 MX 探测，精准识别企业域名邮/自建域名邮/无效域名
            mx_hosts: list[str] = []
            dns_checked = False
            if check_mx:
                mx_hosts, dns_checked = await self.lookup_mx_hosts(domain)

            enterprise_label = self._fingerprint_enterprise_mx(mx_hosts)
            if enterprise_label:
                reasons.append(f"MX 记录 ({', '.join(mx_hosts[:2])}) 指纹识别为：{enterprise_label}")
                return EmailAnalysisResult(
                    email=email,
                    canonical_email=canonical,
                    allowed=False,
                    trust_score=20,
                    category="enterprise_domain_mail",
                    provider=enterprise_label,
                    mx_hosts=mx_hosts,
                    reasons=reasons,
                    summary=(
                        f"不支持自定义域名邮箱注册（检测到 {enterprise_label}），"
                        "请使用 QQ、网易163、Gmail、Outlook 等正规个人邮箱"
                    ),
                )

            if dns_checked and not mx_hosts:
                reasons.append(f"域名 {domain} 无有效 DNS MX 邮件交换记录")
                return EmailAnalysisResult(
                    email=email,
                    canonical_email=canonical,
                    allowed=False,
                    trust_score=5,
                    category="no_mx_domain",
                    provider="无效域名邮箱",
                    mx_hosts=[],
                    reasons=reasons,
                    summary="该邮箱域名无有效邮件服务器记录，禁止注册",
                )

            reasons.append(f"域名 {domain} 不在正规公共个人邮箱提供商白名单中，判定为自定义域名邮箱")
            return EmailAnalysisResult(
                email=email,
                canonical_email=canonical,
                allowed=False,
                trust_score=15 if tld in HIGH_RISK_TLDS else 25,
                category="custom_domain_mail",
                provider="自定义域名邮箱",
                mx_hosts=mx_hosts,
                reasons=reasons,
                summary=(
                    "不支持自定义域名邮箱注册，请使用 QQ、163、126、Gmail、Outlook、iCloud 等正规公共邮箱"
                ),
            )

        # --- 以下进入正规主流公共邮箱深度风控校验 ---
        score = 100
        mx_hosts = []
        if check_mx:
            mx_hosts, dns_checked = await self.lookup_mx_hosts(domain)
            if dns_checked and not mx_hosts:
                score -= 20
                reasons.append("DNS MX 记录暂不可达")

        # Layer 5: Local-Part 防别名绕过与机器批量特征分析
        if strict_registration and "+" in local:
            return EmailAnalysisResult(
                email=email,
                canonical_email=canonical,
                allowed=False,
                trust_score=30,
                category="plus_alias_blocked",
                provider=spec.name,
                mx_hosts=mx_hosts,
                reasons=["检测到 '+' 子地址别名参数，拦截单邮箱批量注册行为"],
                summary="注册邮箱不支持包含 '+' 别名后缀，请使用原始邮箱地址",
            )

        if strict_registration and local in RESERVED_LOCAL_PREFIXES:
            return EmailAnalysisResult(
                email=email,
                canonical_email=canonical,
                allowed=False,
                trust_score=25,
                category="reserved_prefix",
                provider=spec.name,
                mx_hosts=mx_hosts,
                reasons=[f"前缀 {local} 属于系统保留角色名"],
                summary="该邮箱前缀为系统保留名称，不可用于自助注册",
            )

        # QQ 纯数字号段合法性校验
        if domain == "qq.com" and local.isdigit():
            if local.startswith("0") or not (5 <= len(local) <= 11):
                return EmailAnalysisResult(
                    email=email,
                    canonical_email=canonical,
                    allowed=False,
                    trust_score=20,
                    category="invalid_qq_number",
                    provider=spec.name,
                    mx_hosts=mx_hosts,
                    reasons=["纯数字 QQ 邮箱号段不符合 5~11 位非零开头规范"],
                    summary="请输入有效的 QQ 邮箱账号",
                )

        # 香农熵 & 字符类型切换率（防随机脚本批量前缀，例如 x8k2p9q4m7z1v6r3@gmail.com）
        clean_local = local.replace(".", "").replace("_", "").replace("-", "")
        entropy = shannon_entropy(clean_local)
        trans_rate = char_transition_rate(clean_local)
        is_pure_digits = clean_local.isdigit()

        if len(clean_local) < 3:
            score -= 15
            reasons.append("邮箱前缀过短")

        if not is_pure_digits and len(clean_local) >= 16 and entropy >= 3.85 and trans_rate >= 0.45:
            score -= 45
            reasons.append(
                f"前缀疑似随机机器批量生成（长度 {len(clean_local)}，"
                f"信息熵 {entropy:.2f}，字符切换率 {trans_rate:.2f}）"
            )
        elif not is_pure_digits and len(clean_local) >= 20 and entropy >= 4.0:
            score -= 30
            reasons.append(f"前缀信息熵偏高（{entropy:.2f}）")

        score = max(0, min(100, score))
        allowed = score >= 60

        if allowed:
            if not reasons:
                reasons.append(f"已通过正规公共邮箱校验（{spec.name}）")
            summary = f"正规邮箱校验通过（{spec.name}，可信度 {score} 分）"
            category = "mainstream_public"
        else:
            summary = "该邮箱前缀存在异常批量生成特征，请更换常用正规邮箱注册"
            category = "suspicious_local_part"

        return EmailAnalysisResult(
            email=email,
            canonical_email=canonical,
            allowed=allowed,
            trust_score=score,
            category=category,
            provider=spec.name,
            mx_hosts=mx_hosts,
            reasons=reasons,
            summary=summary,
        )


email_trust_analyzer = EmailTrustAnalyzer()
