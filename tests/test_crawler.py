import json

from src.crawler import downloader, extract_metadata, repository_parser
from src.crawler.download_utils import content_is_pdf


def test_split_access_urls_preserves_order_and_removes_duplicates():
    value = "https://example.org/item\ntexto https://example.org/file.pdf https://example.org/item"
    assert downloader.split_access_urls(value) == [
        "https://example.org/item", "https://example.org/file.pdf"
    ]


def test_content_is_pdf_by_signature_or_content_type():
    assert content_is_pdf(b"%PDF-1.7")
    assert content_is_pdf(b"binary", "application/pdf; charset=binary")
    assert not content_is_pdf(b"<html>", "text/html")


def test_extract_record_id():
    url = "https://bdtd.ibict.br/vufind/Record/PUC_SP-1_abc-123"
    assert extract_metadata.extract_record_id(url) == "PUC_SP-1_abc-123"


def test_process_repository_url_contract_for_special_page(tmp_path):
    class Body:
        def inner_text(self, timeout=0):
            return "Tipo de Acesso: Acesso Embargado"

    class Page:
        url = "https://repo.example/item/1"
        def goto(self, *args, **kwargs): pass
        def wait_for_timeout(self, value): pass
        def title(self): return "Documento"
        def locator(self, selector): return Body()

    value = repository_parser.process_repository_url(
        Page(), object(), Page.url, tmp_path / "document.pdf"
    )
    assert set(value) == {"success", "reason", "source_url", "pdf_url", "path"}
    assert value == {
        "success": False, "reason": "restricted_or_embargo",
        "source_url": Page.url, "pdf_url": None, "path": None,
    }


def test_atomic_manifest_write(tmp_path):
    destination = tmp_path / "manifest.json"
    payload = [{"record_id": "abc", "status": "failed"}]
    downloader.save_json(destination, payload)
    assert json.loads(destination.read_text(encoding="utf-8")) == payload
    assert not destination.with_suffix(".json.tmp").exists()


def test_valid_existing_pdf_is_recognized(tmp_path):
    pdf = tmp_path / "existing.pdf"
    pdf.write_bytes(b"%PDF-1.7 existing")
    assert downloader.is_valid_pdf(pdf)
    html = tmp_path / "invalid.pdf"
    html.write_bytes(b"<html>")
    assert not downloader.is_valid_pdf(html)


def test_candidate_filter_rejects_internal_i18n_keys():
    assert repository_parser.score_candidate(
        "https://repo.example/item.edit.bitstreams"
    ) < 0
