from research_assistant.models import DraftClaim, DraftReport, DraftSection, Evidence, Source, utc_now
from research_assistant.reporting import build_report, render_markdown


def test_mixed_invalid_references_are_all_removed_and_html_is_escaped():
    claim = DraftClaim(text="<script>alert(1)</script> https://invented.invalid/fake",
                       evidence_ids=["E1", "invented"], confidence="高", confidence_reason="未知")
    draft = DraftReport(summary=[claim], sections=[DraftSection(title="结论", claims=[claim])],
                        key_conclusions=[claim], unresolved_questions=[])
    source = Source(id="S1", url="https://example.com/", title="真实页面", publisher="example.com", fetched_at=utc_now())
    evidence = Evidence(id="E1", source_id="S1", statement="事实", quote="An actual source quotation.")
    report = build_report("主题", draft, [source], [evidence], False, "完成", {})
    result = report["summary"][0]
    assert result["citations"] == []
    assert result["basis"] == "模型推断"
    assert report["partial"]
    markdown = render_markdown(report)
    assert "https://invented.invalid" not in markdown
    assert "<script>" not in markdown


def test_conflicts_cap_high_confidence():
    claim = DraftClaim(text="存在相互矛盾的证据", evidence_ids=["E1", "E2"], confidence="高", confidence_reason="多来源")
    draft = DraftReport(summary=[claim], sections=[DraftSection(title="冲突", claims=[claim])],
                        key_conclusions=[claim], unresolved_questions=["需继续核验"], conflicts=["来源结论不同"])
    sources = [Source(id=f"S{i}", url=f"https://source{i}.com/", title=f"来源{i}",
                      publisher=f"source{i}.com", fetched_at=utc_now()) for i in (1, 2)]
    evidence = [Evidence(id=f"E{i}", source_id=f"S{i}", statement="证据", quote="Actual source text.") for i in (1, 2)]
    report = build_report("主题", draft, sources, evidence, False, "完成", {})
    assert report["summary"][0]["confidence"] == "中"
    assert report["conflicts"] == ["来源结论不同"]
