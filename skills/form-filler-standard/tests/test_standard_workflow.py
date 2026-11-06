"""Synthetic end-to-end tests of the standard deidentification/proposal/fill flow."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from privacy import PrivacyError, private_text
from standard_workflow import prepare_case, review_response, apply_review, request_digest, Deidentifier
from cloud_draft import send_request


@pytest.fixture
def case(tmp_path):
    template = tmp_path / "SYNTHETIC_PRIVATE_FILENAME.docx"
    doc = Document()
    table = doc.add_table(rows=3, cols=2)
    for row, label in zip(table.rows, ["年级", "申请理由", "姓名"]):
        row.cells[0].text = label
    table.cell(2, 1).text = "SYNTHETIC_NAME"
    doc.save(template)
    source = {
        "facts": [
            {"id": "F1", "kind": "education", "text": "SYNTHETIC_NAME在SYNTHETIC_SCHOOL学习化学，本科二年级。", "allow_cloud": True},
            {"id": "F2", "kind": "experience", "text": "参与课程实验，电话13812345678，邮箱test@example.edu。", "allow_cloud": True},
            {"id": "F3", "kind": "experience", "text": "SYNTHETIC_NOT_AUTHORIZED_MATERIAL", "allow_cloud": False},
        ],
        "replacements": {"{{PERSON_1}}": "SYNTHETIC_NAME", "{{SCHOOL_1}}": "SYNTHETIC_SCHOOL"},
        "targets": [
            {"id": "T1", "table": 0, "row": 0, "col": 1, "kind": "infer", "label": "年级", "requirements": "根据F1给出年级", "min_chars": 0, "max_chars": 20},
            {"id": "T2", "table": 0, "row": 1, "col": 1, "kind": "generate", "label": "申请理由", "requirements": "为SYNTHETIC_NAME组织申请理由，不增加新经历", "min_chars": 0, "max_chars": 300},
        ],
    }
    source_path = tmp_path / "case.json"
    private_text(source_path, json.dumps(source, ensure_ascii=False))
    return tmp_path, source, source_path, template


def prepare(case):
    root, _, source_path, template = case
    req, plan = root / "request.json", root / "plan.json"
    digest = prepare_case(source_path, template, "https://provider.example/v1", "synthetic-model", req, plan, now=1000)
    return req, plan, digest


def response(root, **changes):
    items = [
        {"target_id": "T1", "value": "本科二年级", "basis": ["F1"], "assumptions": [], "confidence": "high"},
        {"target_id": "T2", "value": "{{PERSON_1}}在{{SCHOOL_1}}学习化学，参与课程实验。", "basis": ["F1", "F2"], "assumptions": [], "confidence": "high"},
    ]
    items[1].update(changes)
    path = root / "response.txt"
    private_text(path, json.dumps({"items": items}, ensure_ascii=False))
    return path


def test_actual_outbound_body_has_no_original_identifiers_or_document_data(case, monkeypatch):
    root, _, source_path, template = case
    req, plan, digest = prepare(case)
    text = req.read_text(encoding="utf-8")
    for secret in ["SYNTHETIC_NAME", "SYNTHETIC_SCHOOL", "13812345678", "test@example.edu", "SYNTHETIC_PRIVATE_FILENAME", "SYNTHETIC_NOT_AUTHORIZED_MATERIAL"]:
        assert secret not in text
    for token in ["{{PERSON_1}}", "{{SCHOOL_1}}", "{{PRIVATE_1}}"]:
        assert token in text
    assert "replacements" not in text and '"table"' not in text
    assert "SYNTHETIC_NAME" in plan.read_text(encoding="utf-8")
    sent = []
    real_client = httpx.Client
    def reply(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": response(root).read_text(encoding="utf-8")}}]})
    monkeypatch.setenv("FORM_FILLER_CLOUD_API_KEY", "SYNTHETIC_TOKEN")
    draft = root / "cloud_response.txt"
    with patch.object(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw)):
        send_request(req, digest, draft, now=1001)
    assert len(sent) == 1
    body = json.loads(sent[0].content)
    assert "SYNTHETIC_NAME" not in json.dumps(body)
    before = template.read_bytes()
    review = root / "review.json"
    approved = review_response(plan, req, draft, review)
    assert template.read_bytes() == before
    local_review = json.loads(review.read_text(encoding="utf-8"))
    assert local_review["items"][0]["status"] == "待用户确认的推测"
    assert "SYNTHETIC_NAME" in local_review["items"][1]["value"]
    out = root / "filled.docx"
    assert apply_review(review, approved, ["T2"], out) == 1
    result = Document(out)
    assert result.tables[0].cell(0, 1).text == ""  # unaccepted inference stays empty
    assert "SYNTHETIC_NAME" in result.tables[0].cell(1, 1).text
    assert result.tables[0].cell(2, 1).text == "SYNTHETIC_NAME"  # existing local identity preserved
    assert template.read_bytes() == before


@pytest.mark.parametrize("field,kind", [("籍贯", "infer"), ("出生日期", "infer"), ("政治面貌", "infer"), ("姓名", "generate"), ("身份证号", "generate")])
def test_protected_identity_fields_cannot_be_inferred_or_generated(case, field, kind):
    root, source, source_path, template = case
    source["targets"][0].update(label=field, kind=kind)
    private_text(source_path, json.dumps(source))
    with pytest.raises(PrivacyError):
        prepare(case)
    assert not (root / "request.json").exists()


@pytest.mark.parametrize("changes", [
    {"value": "{{UNKNOWN_PERSON}}"}, {"value": "{{broken}}"}, {"value": "联系13812345678"},
    {"value": "SYNTHETIC_NAME"}, {"basis": ["F3"]}, {"basis": []}, {"confidence": "certain"},
    {"target_id": "T999"}, {"value": "A" * 301},
])
def test_unusable_model_output_is_blocked_before_filling(case, changes):
    root = case[0]
    req, plan, _ = prepare(case)
    raw = response(root, **changes)
    with pytest.raises(PrivacyError):
        review_response(plan, req, raw, root / "review.json")
    assert not (root / "review.json").exists()
    assert not (root / "filled.docx").exists()


@pytest.mark.parametrize("mutation", ["approval", "review", "template", "selected"])
def test_apply_binds_approval_review_and_original_template(case, mutation):
    root, _, _, template = case
    req, plan, _ = prepare(case)
    raw = response(root)
    review = root / "review.json"
    digest = review_response(plan, req, raw, review)
    selected = ["T1", "T2"]
    if mutation == "approval":
        digest = "0" * 64
    elif mutation == "review":
        data = json.loads(review.read_text(encoding="utf-8"))
        data["items"][0]["value"] = "博士三年级"
        private_text(review, json.dumps(data))
    elif mutation == "template":
        doc = Document(template)
        doc.tables[0].cell(0, 1).text = "User changed value"
        doc.save(template)
    else:
        selected = []
    before = template.read_bytes()
    with pytest.raises(PrivacyError):
        apply_review(review, digest, selected, root / "filled.docx")
    assert template.read_bytes() == before
    assert not (root / "filled.docx").exists()


def test_accepted_inference_fills_locally_with_its_review_status(case):
    root = case[0]
    req, plan, _ = prepare(case)
    review = root / "review.json"
    digest = review_response(plan, req, response(root), review)
    assert apply_review(review, digest, ["T1", "T2"], root / "filled.docx") == 2
    assert Document(root / "filled.docx").tables[0].cell(0, 1).text == "本科二年级"


def test_overlapping_or_occupied_targets_preserve_existing_data(case):
    root, source, source_path, _ = case
    source["targets"][0].update(row=2)
    private_text(source_path, json.dumps(source))
    with pytest.raises(PrivacyError):
        prepare(case)
    assert not (root / "request.json").exists()


def test_common_labeled_identifiers_are_masked_locally():
    deid = Deidentifier({})
    output = deid.redact("姓名：合成人名；籍贯：合成市，手机13812345678，邮箱synth@example.edu")
    for original in ["合成人名", "合成市", "13812345678", "synth@example.edu"]:
        assert original not in output
        assert original in deid.mapping.values()


def test_draft_retains_visible_uncertainty_markers(case):
    root = case[0]
    req, plan, _ = prepare(case)
    review = root / "review.json"
    digest = review_response(plan, req, response(root), review)
    apply_review(review, digest, ["T1", "T2"], root / "draft.docx", draft=True)
    doc = Document(root / "draft.docx")
    assert doc.tables[0].cell(0, 1).text.startswith("【待确认推测】")
    assert doc.tables[0].cell(1, 1).text.startswith("【AI生成草稿】")


def test_long_identifiers_and_common_secrets_are_masked():
    values = ["123456789012345678901234", "sk-syntheticsecretvalue", "ghp_syntheticsecretvalue"]
    deid = Deidentifier({})
    text = deid.redact(" / ".join(values))
    assert all(value not in text for value in values)
    assert set(values) <= set(deid.mapping.values())


def test_target_label_cannot_disguise_a_different_template_field(case):
    root, source, source_path, _ = case
    source["targets"][0].update(label="自我评价", kind="generate")
    private_text(source_path, json.dumps(source))
    with pytest.raises(PrivacyError):
        prepare(case)
    assert not (root / "request.json").exists()


def test_apply_preserves_empty_target_formatting(case):
    from docx.shared import Pt
    root, _, _, template = case
    doc = Document(template)
    paragraph = doc.tables[0].cell(1, 1).paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(9)
    run = paragraph.add_run("")
    run.bold = True
    run.font.size = Pt(14)
    doc.save(template)
    req, plan, _ = prepare(case)
    review = root / "review.json"
    digest = review_response(plan, req, response(root), review)
    apply_review(review, digest, ["T2"], root / "filled.docx")
    paragraph = Document(root / "filled.docx").tables[0].cell(1, 1).paragraphs[0]
    assert paragraph.paragraph_format.space_after == Pt(9)
    assert paragraph.runs[0].bold is True
    assert paragraph.runs[0].font.size == Pt(14)


def test_nested_table_is_not_a_blank_target(case):
    root, _, _, template = case
    doc = Document(template)
    doc.tables[0].cell(0, 1).add_table(rows=1, cols=1).cell(0, 0).text = "Existing nested content"
    doc.save(template)
    before = template.read_bytes()
    with pytest.raises(PrivacyError):
        prepare(case)
    assert not (root / "request.json").exists()
    assert template.read_bytes() == before


@pytest.mark.parametrize("later_source", ["fact", "requirements", "unselected_fact"])
def test_identity_discovered_later_masks_all_earlier_facts(case, later_source):
    root, source, source_path, _ = case
    source["replacements"] = {}
    source["facts"] = [{"id": "F1", "kind": "experience", "text": "合成甲同学参与实验。", "allow_cloud": True}]
    if later_source == "requirements":
        source["targets"][1]["requirements"] = "姓名：合成甲同学。只组织已知事实。"
    else:
        source["facts"].append({"id": "F2", "kind": "experience", "text": "姓名：合成甲同学。", "allow_cloud": later_source == "fact"})
    private_text(source_path, json.dumps(source, ensure_ascii=False))
    req, plan, _ = prepare(case)
    assert "合成甲同学" not in req.read_text(encoding="utf-8")
    assert "合成甲同学" in json.loads(plan.read_text(encoding="utf-8"))["replacements"].values()
    if later_source == "unselected_fact":
        assert "F2" not in req.read_text(encoding="utf-8")


@pytest.mark.parametrize("phone", ["138-1234-5678", "138 1234 5678", "+86 138 1234 5678", "138\u200b1234\u200b5678", "+1 (202) 555-0123"])
def test_formatted_contact_numbers_are_redacted(phone):
    deid = Deidentifier({})
    text = deid.redact("联系方式为" + phone)
    assert phone not in text
    assert phone in deid.mapping.values()


def test_replacements_never_rewrite_an_inserted_or_existing_token():
    deid = Deidentifier({"{{PERSON_1}}": "PRIVATE", "{{PRIVATE_1}}": "13812345678"})
    result = deid.redact("PRIVATE的电话为13812345678，已有{{PERSON_1}}。")
    assert result == "{{PERSON_1}}的电话为{{PRIVATE_1}}，已有{{PERSON_1}}。"
    deid.assert_no_identifiers(result)


def test_restoration_validation_ignores_known_values_inside_placeholder_names(case):
    root, source, source_path, _ = case
    source["replacements"] = {"{{PERSON_1}}": "PRIVATE"}
    private_text(source_path, json.dumps(source))
    req, plan, _ = prepare(case)
    raw = response(root, value="{{PERSON_1}}参与课程实验。")
    digest = review_response(plan, req, raw, root / "review.json")
    assert digest
    data = json.loads((root / "review.json").read_text(encoding="utf-8"))
    assert data["items"][1]["value"] == "PRIVATE参与课程实验。"


def test_large_valid_review_can_be_applied(tmp_path):
    source = {
        "facts": [{"id": "F" + str(i), "kind": "experience", "text": "课程实验经验" * 500, "allow_cloud": True} for i in range(1, 4)],
        "replacements": {},
        "targets": [{"id": "T" + str(i+1), "table": 0, "row": i, "col": 1, "kind": "generate", "label": "申请理由", "requirements": "仅整理已有实验经历", "min_chars": 0, "max_chars": 100} for i in range(7)],
    }
    template = tmp_path / "template.docx"
    doc = Document()
    table = doc.add_table(rows=7, cols=2)
    for row in table.rows:
        row.cells[0].text = "申请理由"
    doc.save(template)
    source_path, req, plan = tmp_path / "source.json", tmp_path / "request.json", tmp_path / "plan.json"
    private_text(source_path, json.dumps(source, ensure_ascii=False))
    prepare_case(source_path, template, "https://provider.example/v1", "synthetic", req, plan, now=1000)
    raw = tmp_path / "response.txt"
    private_text(raw, json.dumps({"items": [{"target_id": "T" + str(i+1), "value": "积极学习实验知识。", "basis": ["F1", "F2", "F3"], "assumptions": [], "confidence": "medium"} for i in range(7)]}, ensure_ascii=False))
    review = tmp_path / "review.json"
    digest = review_response(plan, req, raw, review)
    assert review.stat().st_size > 131_072
    assert apply_review(review, digest, ["T1"], tmp_path / "filled.docx") == 1


def test_prepare_binds_fingerprint_to_the_same_bytes_that_were_parsed(case, monkeypatch):
    import hashlib
    import standard_workflow as workflow
    root, _, _, template = case
    original = template.read_bytes()
    real_document = workflow.Document
    def concurrent_change(snapshot):
        assert hasattr(snapshot, "read")
        edited = real_document(template)
        edited.tables[0].cell(0, 0).text = "并发修改的标签"
        edited.save(template)
        return real_document(snapshot)
    monkeypatch.setattr(workflow, "Document", concurrent_change)
    req, plan, _ = prepare(case)
    data = json.loads(plan.read_text(encoding="utf-8"))
    assert data["template_sha256"] == hashlib.sha256(original).hexdigest()
    assert data["template_sha256"] != hashlib.sha256(template.read_bytes()).hexdigest()


def test_apply_parses_the_same_template_bytes_it_verified(case, monkeypatch):
    import standard_workflow as workflow
    root, _, _, template = case
    req, plan, _ = prepare(case)
    review = root / "review.json"
    digest = review_response(plan, req, response(root), review)
    real_document = workflow.Document
    def concurrent_change(snapshot):
        assert hasattr(snapshot, "read")
        edited = real_document(template)
        edited.tables[0].cell(0, 0).text = "并发修改的标签"
        edited.save(template)
        return real_document(snapshot)
    monkeypatch.setattr(workflow, "Document", concurrent_change)
    output = root / "filled.docx"
    apply_review(review, digest, ["T1"], output)
    assert real_document(output).tables[0].cell(0, 0).text == "年级"
    assert real_document(template).tables[0].cell(0, 0).text == "并发修改的标签"
