import hashlib
import json
from datetime import date
from urllib.parse import urlparse

from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .errors import ServiceError
from .models import LegalEdition

OFFICIAL_HOSTS = {"law.go.kr", "www.law.go.kr", "copyright.or.kr", "www.copyright.or.kr"}


def eligible(edition: LegalEdition, as_of: date) -> bool:
    parsed = urlparse(edition.official_url)
    return bool(
        edition.reviewed
        and parsed.scheme == "https"
        and parsed.hostname in OFFICIAL_HOSTS
        and parsed.username is None
        and edition.published_on
        and edition.published_on <= as_of
        and edition.retrieved_on
        and edition.retrieved_on <= as_of
        and edition.effective_from
        and edition.effective_from <= as_of
        and (edition.effective_to is None or as_of <= edition.effective_to)
        and hashlib.sha256(edition.content.encode("utf-8")).hexdigest() == edition.sha256
    )


def load_catalog(settings: Settings, as_of: date | None = None) -> list[LegalEdition]:
    try:
        rows = TypeAdapter(list[LegalEdition]).validate_python(
            json.loads(settings.legal_catalog.read_text(encoding="utf-8"))
        )
        if len({row.source_id for row in rows}) != len(rows):
            raise ValueError("duplicate legal source_id")
        return [row for row in rows if eligible(row, as_of or date.today())]
    except (OSError, ValueError, ValidationError) as exc:
        raise ServiceError("LEGAL_CATALOG_INVALID", "법률자료 판본 파일을 확인하세요", 503) from exc
