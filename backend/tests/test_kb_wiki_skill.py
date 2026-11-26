from __future__ import annotations

import io
import json
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_v12_features import _login_admin, _parse_sse_events


def _build_minimal_docx(paragraphs: list[str]) -> bytes:
    p_xml = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for text in paragraphs
    )
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{p_xml}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_llm_wiki_build_publish_export_import_and_chat_invocation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_headers = await _login_admin(client)

        # 1. 创建 LLM Wiki 知识库
        create_res = await client.post(
            "/api/v1/kb/bases",
            json={
                "name": "亲密关系依恋手册",
                "slug": "attachment-handbook",
                "description": "讲解安全型、焦虑型与回避型依恋的沟通方法",
                "visibility": "private",
            },
            headers=admin_headers,
        )
        assert create_res.status_code == 200
        kb = create_res.json()["data"]
        kb_id = kb["id"]
        assert "Schema" in kb["schema_md"]

        # 2. 上传本地 .md + .docx 文件（含一次重复校验）
        md_content = (
            "# 回避型依恋沟通策略\n\n"
            "## 为什么回避型伴侣总是冷处理\n"
            "当面对高强度情绪压迫时，回避型依恋的人会触发防御撤退机制，需要留出冷静空间。\n\n"
            "## 三步安全感破冰话术\n"
            "先认可对方需求，再明确表达边界与期望时间节点，例如：等你忙完我们聊十分钟好吗。\n"
        ).encode()
        docx_bytes = _build_minimal_docx(
            ["焦虑型依恋自救指南", "当出现已读不回时，先做五分钟深呼吸，避免连环追问。"]
        )

        up_res = await client.post(
            f"/api/v1/kb/bases/{kb_id}/sources",
            files=[
                ("files", ("avoidant_guide.md", md_content, "text/markdown")),
                (
                    "files",
                    (
                        "anxious_notes.docx",
                        docx_bytes,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
            ],
            data={"auto_compile": "false", "use_llm": "false"},
            headers=admin_headers,
        )
        assert up_res.status_code == 200
        assert up_res.json()["data"]["uploaded"] == 2

        dup_res = await client.post(
            f"/api/v1/kb/bases/{kb_id}/sources",
            files=[("files", ("avoidant_guide.md", md_content, "text/markdown"))],
            headers=admin_headers,
        )
        assert dup_res.status_code == 200
        assert dup_res.json()["data"]["deduplicated"] == 1

        # 3. 执行 LLM Wiki 编译入库 (Ingest)
        comp_res = await client.post(
            f"/api/v1/kb/bases/{kb_id}/compile",
            json={"use_llm": False},
            headers=admin_headers,
        )
        assert comp_res.status_code == 200
        comp_data = comp_res.json()["data"]
        assert comp_data["compiled_sources"] == 2
        assert comp_data["generated_pages"] >= 3
        assert "[[回避型依恋沟通策略]]" in comp_data["kb"]["index_md"]
        assert "ingest |" in comp_data["kb"]["log_md"]

        # 4. 执行 Wiki 健康体检 (Lint) & 回流洞察 (Insight)
        lint_res = await client.post(f"/api/v1/kb/bases/{kb_id}/lint", headers=admin_headers)
        assert lint_res.status_code == 200
        lint_report = lint_res.json()["data"]
        assert lint_report["total_pages"] >= 4
        assert lint_report["pending_sources"] == []

        insight_res = await client.post(
            f"/api/v1/kb/bases/{kb_id}/insights",
            json={
                "title": "冷战前 24 小时降噪法则",
                "content": "结合 [[回避型依恋沟通策略]]，冲突发生前 24 小时优先安抚而不是逼问结论。",
                "source_question": "冷战了怎么办",
            },
            headers=admin_headers,
        )
        assert insight_res.status_code == 200
        assert "wiki/insights/" in insight_res.json()["data"]["page"]["page_path"]

        # 5. 发布为可调用 Skill，并测试检索与导出 .zip 整包
        pub_res = await client.post(
            f"/api/v1/kb/bases/{kb_id}/skill/publish",
            json={
                "name": "依恋关系军师Skill",
                "slug": "attachment-coach",
                "description": "基于依恋类型给出沟通策略",
                "triggers": ["回避型依恋", "冷处理", "焦虑型"],
                "visibility": "private",
                "is_enabled": True,
            },
            headers=admin_headers,
        )
        assert pub_res.status_code == 200
        skill = pub_res.json()["data"]
        assert skill["slug"] == "attachment-coach"
        assert "triggers:" in skill["skill_md"]

        tq_res = await client.post(
            f"/api/v1/kb/skills/{skill['id']}/test-query",
            json={"query": "回避型伴侣总冷处理怎么办", "top_k": 4},
            headers=admin_headers,
        )
        assert tq_res.status_code == 200
        citations = tq_res.json()["data"]["citations"]
        assert len(citations) >= 1
        assert any("回避型" in c["title"] for c in citations)

        exp_res = await client.get(
            f"/api/v1/kb/bases/{kb_id}/export-skill",
            headers=admin_headers,
        )
        assert exp_res.status_code == 200
        assert exp_res.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(exp_res.content)) as zf:
            names = set(zf.namelist())
            assert {"SKILL.md", "SCHEMA.md", "index.md", "log.md", "manifest.json"} <= names
            assert any(n.startswith("wiki/") for n in names)
            assert any(n.startswith("raw/") for n in names)

        # 6. 通过对话接口显式 / 命令 / 自动触发调用该 Skill
        chat_res = await client.post(
            "/api/v1/ai/chat",
            json={
                "message": "回避型依恋伴侣总喜欢冷处理怎么办？",
                "auto_match_skills": True,
                "incognito": True,
            },
            headers=admin_headers,
        )
        assert chat_res.status_code == 200
        chat_data = chat_res.json()["data"]
        assert len(chat_data["invoked_skills"]) == 1
        assert chat_data["invoked_skills"][0]["slug"] == "attachment-coach"
        assert len(chat_data["invoked_skills"][0]["citations"]) >= 1
        assert "依恋关系军师Skill" in chat_data["reply"]

        stream_res = await client.post(
            "/api/v1/ai/chat/stream",
            json={
                "message": "/skill:attachment-coach 帮我总结三步破冰话术",
                "skill_ids": [skill["id"]],
                "incognito": True,
            },
            headers=admin_headers,
        )
        assert stream_res.status_code == 200
        events = _parse_sse_events(stream_res.text)
        meta_ev = next(e for e in events if e.get("event") == "meta")
        assert len(meta_ev["invoked_skills"]) == 1
        assert meta_ev["invoked_skills"][0]["slug"] == "attachment-coach"

        # 7. 小程序独立用户整包导入 .zip 并隔离权限校验
        wx_res = await client.post(
            "/api/v1/miniapp/auth/wx-login",
            json={"code": "kb_bundle_tester", "nickname": "小知测"},
        )
        assert wx_res.status_code == 200
        wx_headers = {"Authorization": f"Bearer {wx_res.json()['data']['access_token']}"}

        # 跨账号访问管理员私有 KB 必须返回 403
        forbidden_res = await client.get(f"/api/v1/kb/bases/{kb_id}", headers=wx_headers)
        assert forbidden_res.status_code == 403

        # 小程序用户上传刚才导出的完整 Skill .zip 包
        imp_res = await client.post(
            "/api/v1/kb/import-bundle",
            files=[("bundle_zip", ("exported-skill.zip", exp_res.content, "application/zip"))],
            data={
                "name": "我的云端副本知识库",
                "visibility": "private",
                "auto_compile": "true",
                "use_llm": "false",
            },
            headers=wx_headers,
        )
        assert imp_res.status_code == 200
        imp_data = imp_res.json()["data"]
        assert imp_data["imported_raw"] >= 2
        assert imp_data["imported_wiki"] >= 4
        assert imp_data["skill"]["is_enabled"] is True

        # 验证可通过 GET /kb/skills 查到自己的 Skill 并直接对话调用
        list_sk = await client.get("/api/v1/kb/skills", headers=wx_headers)
        assert list_sk.status_code == 200
        assert any(s["id"] == imp_data["skill"]["id"] for s in list_sk.json()["data"]["items"])

        # 8. 多文件直传整包（本地文件夹含 SKILL.md + 原始文本自动编译）+ Zip Slip 防护校验
        custom_skill_md = (
            "---\n"
            "name: 约会流程宝典\n"
            "slug: date-playbook\n"
            "description: 第一次见面的约会动线安排\n"
            "triggers:\n  - 约会动线\n  - 首次见面\n"
            "---\n\n# 约会流程宝典\n优先参考餐厅与转场建议。\n"
        ).encode()
        date_doc = "# 首次见面选址\n## 咖啡馆转场\n优先安静半开放座位。\n".encode()
        folder_res = await client.post(
            "/api/v1/kb/import-bundle",
            files=[
                ("files", ("SKILL.md", custom_skill_md, "text/markdown")),
                ("files", ("first_date.md", date_doc, "text/markdown")),
            ],
            data={
                "rel_paths_json": json.dumps(["SKILL.md", "raw/first_date.md"]),
                "visibility": "public",
                "auto_compile": "true",
                "use_llm": "false",
            },
            headers=wx_headers,
        )
        assert folder_res.status_code == 200
        assert folder_res.json()["data"]["imported_wiki"] >= 2

        # 构造 Zip Slip 恶意压缩包拦截校验
        bad_zip_buf = io.BytesIO()
        with zipfile.ZipFile(bad_zip_buf, "w") as zf:
            zf.writestr("../../etc/passwd", "root:x:0:0")
        bad_res = await client.post(
            "/api/v1/kb/import-bundle",
            files=[("bundle_zip", ("evil.zip", bad_zip_buf.getvalue(), "application/zip"))],
            headers=wx_headers,
        )
        assert bad_res.status_code == 400
