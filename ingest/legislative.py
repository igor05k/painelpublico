#!/usr/bin/env python3
"""Import official federal Câmara and Senado legislative expense data.

The script keeps complete source rows in the output. It uses only the Python
standard library and stores the public source snapshots under data/raw.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "legislative"
CHAMBER_CEAP_URL = "https://www.camara.leg.br/cotas/Ano-{year}.csv.zip"
CHAMBER_DEPUTIES_URL = (
    "https://dadosabertos.camara.leg.br/api/v2/deputados?itens=100&pagina=1"
)
SENATE_CEAPS_URL = (
    "https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/"
    "despesas_ceaps/{year}"
)
SENATE_ROSTER_URL = "https://legis.senado.leg.br/dadosabertos/senador/lista/atual"
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
# Mesmos valores de backend/config.py: o complemento de moradia da CEAP fica fora da cota.
HOUSING_COMPLEMENT_CATEGORY = "COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA"
HOUSING_COMPLEMENT_KIND = "complemento_moradia"
# Companhia aérea citada no detalhamento das passagens do Senado ("Companhia Aérea: LATAM, Localizador: ...").
# Só o nome da companhia é guardado; passageiros, matrículas e localizadores não.
AIRLINE_IN_DETAIL = re.compile(r"Companhia A[ée]rea:\s*([^,;\n]+)", re.IGNORECASE)
AIRLINES = {"LATAM": "LATAM", "TAM": "LATAM", "GOL": "GOL", "AZUL": "AZUL", "AZUL 1": "AZUL"}


def ticket_airline(detail: Any) -> str | None:
    """Companhia aérea reconhecida no detalhamento; outros nomes (ex.: a própria agência) não contam."""
    match = AIRLINE_IN_DETAIL.search(str(detail or ""))
    return AIRLINES.get(match.group(1).strip().upper()) if match else None


CPF_IN_NAME = re.compile(
    r"(?<![A-Za-z0-9])(?:CPF\s*[:#-]?\s*)?(?:\d{11}|\d{3}\.\d{3}\.\d{3}-\d{2})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
AMBIGUOUS_11_DIGIT_ID = re.compile(
    r"(?:\d{11}|\d{3}\.\d{3}\.\d{3}-\d{2})"
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def download(
    url: str,
    destination: Path,
    accept: str = "application/json, text/csv, application/xml, */*",
) -> bytes:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        content = response.read()
    if not content:
        raise ValueError(f"Official source returned an empty response: {url}")
    destination.write_bytes(content)
    return content


def request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object from {url}")
    return payload


def fetch_chamber_roster() -> tuple[list[dict[str, Any]], int, str]:
    """Follow the official API's next links until the roster is exhausted."""
    first_url = CHAMBER_DEPUTIES_URL
    current_url = first_url
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    page_count = 0
    while current_url:
        if current_url in seen:
            raise ValueError(f"Câmara roster pagination repeated URL: {current_url}")
        seen.add(current_url)
        response = request_json(current_url)
        page_count += 1
        data = response.get("dados")
        if not isinstance(data, list):
            raise ValueError(f"Câmara roster page has no data array: {current_url}")
        rows.extend(item for item in data if isinstance(item, dict))
        links = response.get("links", [])
        next_link = next(
            (link.get("href") for link in links if link.get("rel") == "next"),
            None,
        )
        current_url = urllib.parse.urljoin(current_url, next_link) if next_link else ""

        page_path = RAW_DIR / f"camara-deputies-page-{page_count}.json"
        page_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")

    if not rows:
        raise ValueError("Official Câmara roster contained no deputies")
    return rows, page_count, first_url


def norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_identifier(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def valid_numeric_cnpj(value: str) -> bool:
    """Validate the two numeric CNPJ check digits."""
    if not re.fullmatch(r"\d{14}", value) or len(set(value)) == 1:
        return False

    def check_digit(base: str, weights: tuple[int, ...]) -> str:
        total = sum(int(char) * weight for char, weight in zip(base, weights))
        remainder = total % 11
        return "0" if remainder < 2 else str(11 - remainder)

    first = check_digit(value[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    second = check_digit(value[:12] + first, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return value[-2:] == first + second


def sanitize_supplier_name(value: Any) -> tuple[str | None, int]:
    if value is None:
        return None, 0
    original = str(value)
    matches = len(CPF_IN_NAME.findall(original))
    cleaned = CPF_IN_NAME.sub(" ", original)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None, matches


def source_specific_identifier_key(source: str, identifier: Any) -> str:
    normalized = normalize_identifier(identifier)
    digest = hashlib.sha256(f"{source}:{normalized}".encode("utf-8")).hexdigest()
    return f"{source}:id-sha256:{digest}"


def source_specific_name_key(source: str, name: Any) -> str:
    normalized = norm_name(name)
    digest = hashlib.sha256(f"{source}:name:{normalized}".encode("utf-8")).hexdigest()
    return f"{source}:name-sha256:{digest}"


def is_ambiguous_document_id(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(AMBIGUOUS_11_DIGIT_ID.fullmatch(text) or CPF_IN_NAME.fullmatch(text))


def stable_expense_content(expense: dict[str, Any]) -> dict[str, Any]:
    supplier = expense.get("supplier") if isinstance(expense.get("supplier"), dict) else {}
    document_id = expense.get("documentId")
    if is_ambiguous_document_id(document_id):
        document_id = None
    try:
        amount = format(Decimal(str(expense.get("amount", 0))).normalize(), "f")
    except (InvalidOperation, ValueError):
        amount = str(expense.get("amount", 0)).strip()
    return {
        "authorityId": str(expense.get("authorityId") or ""),
        "sourceId": str(expense.get("sourceId") or ""),
        "year": int_or_none(expense.get("year")),
        "month": int_or_none(expense.get("month")),
        "date": parse_date(expense.get("date")),
        "category": norm_name(expense.get("category")) or None,
        "amount": amount,
        "documentId": re.sub(r"\s+", " ", str(document_id or "").strip()) or None,
        "documentUrl": str(expense.get("documentUrl") or "").strip() or None,
        "supplier": {
            "key": str(supplier.get("key") or ""),
            "name": norm_name(supplier.get("name")) or None,
            "cnpj": supplier.get("cnpj"),
        },
    }


def assign_stable_expense_ids(
    expenses: list[dict[str, Any]], source_id: str, native_ids: list[Any]
) -> dict[str, int]:
    """Use unique source row IDs, then content fingerprints with duplicate ordinals."""
    if len(expenses) != len(native_ids):
        raise ValueError("Expense/native ID count mismatch")
    candidates = [
        str(native_id or "").strip()
        if not is_ambiguous_document_id(native_id)
        else ""
        for native_id in native_ids
    ]
    frequencies: dict[str, int] = {}
    for candidate in candidates:
        if candidate:
            frequencies[candidate] = frequencies.get(candidate, 0) + 1
    fingerprint_ordinals: dict[str, int] = {}
    stats = {"persistentIdRows": 0, "fingerprintRows": 0, "duplicateNativeIdRows": 0}
    for expense, candidate in zip(expenses, candidates):
        if candidate and frequencies[candidate] == 1:
            expense["id"] = f"{source_id}:record:{candidate}"
            stats["persistentIdRows"] += 1
            continue
        if candidate:
            stats["duplicateNativeIdRows"] += 1
        content = stable_expense_content(expense)
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        ordinal = fingerprint_ordinals.get(fingerprint, 0) + 1
        fingerprint_ordinals[fingerprint] = ordinal
        expense["id"] = f"{source_id}:fingerprint:{fingerprint}:{ordinal}"
        stats["fingerprintRows"] += 1
    return stats


def int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_amount(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace("R$", "").replace("\u00a0", "")
    text = re.sub(r"\s+", "", text)
    if not text:
        raise ValueError("monetary amount is missing")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    return float(text)


def parse_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text[:10]
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    return None


def date_br(value: str | None) -> str:
    if not value:
        return "data não informada"
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return value


def supplier_fields(name: Any, raw_tax_id: Any, source: str, row_index: int) -> dict[str, Any]:
    supplier_name, _ = sanitize_supplier_name(name)
    raw_identifier = str(raw_tax_id or "").strip()
    tax_digits = digits(raw_tax_id)
    normalized_identifier = normalize_identifier(raw_identifier)
    if len(tax_digits) == 14 and valid_numeric_cnpj(tax_digits):
        return {
            "key": tax_digits,
            "name": supplier_name,
            "cnpj": tax_digits,
        }
    if len(tax_digits) == 11:
        key = hashlib.sha256(tax_digits.encode("ascii")).hexdigest()
        return {"key": f"cpf-sha256:{key}", "name": supplier_name, "cnpj": None}
    if normalized_identifier:
        return {
            "key": source_specific_identifier_key(source, raw_identifier),
            "name": supplier_name,
            "cnpj": None,
        }
    normalized = norm_name(supplier_name)
    if normalized:
        return {"key": source_specific_name_key(source, supplier_name), "name": supplier_name, "cnpj": None}
    return {
        "key": f"{source}:unknown",
        "name": None,
        "cnpj": None,
    }


def sanitize_expense_suppliers(expenses: list[dict[str, Any]]) -> dict[str, int]:
    """Sanitize existing supplier objects without changing expense identity or amounts."""
    stats = {
        "namesWithCpfText": 0,
        "cpfNameMatchesRemoved": 0,
        "invalidCnpjValues": 0,
        "validCnpjValues": 0,
        "nameKeysRehashed": 0,
    }
    for expense in expenses:
        supplier = expense.get("supplier")
        if not isinstance(supplier, dict):
            continue
        source_id = str(expense.get("sourceId") or "")
        source = "camara" if source_id.startswith("camara") else "senado" if source_id.startswith("senado") else "source"
        original_name = supplier.get("name")
        cleaned_name, matches = sanitize_supplier_name(original_name)
        if matches:
            stats["namesWithCpfText"] += 1
            stats["cpfNameMatchesRemoved"] += matches
            supplier["name"] = cleaned_name
        elif original_name is not None:
            supplier["name"] = cleaned_name

        key = str(supplier.get("key") or "")
        cnpj_value = str(supplier.get("cnpj") or "").strip()
        candidate = digits(cnpj_value)
        if len(candidate) != 14 and re.fullmatch(r"\d{14}", key):
            candidate = key
        if len(candidate) == 14:
            if valid_numeric_cnpj(candidate):
                supplier["cnpj"] = candidate
                supplier["key"] = candidate
                stats["validCnpjValues"] += 1
            else:
                stats["invalidCnpjValues"] += 1
                supplier["cnpj"] = None
                supplier["key"] = source_specific_identifier_key(source, candidate)
        elif cnpj_value:
            stats["invalidCnpjValues"] += 1
            supplier["cnpj"] = None
            supplier["key"] = source_specific_identifier_key(source, cnpj_value)
        elif key.startswith(f"{source}:name-sha256:"):
            if cleaned_name:
                new_key = source_specific_name_key(source, cleaned_name)
            else:
                new_key = f"{source}:unknown:{expense.get('id') or 'no-row-id'}"
            if new_key != key:
                stats["nameKeysRehashed"] += 1
                supplier["key"] = new_key
    return stats


def chamber_authority_id(row: dict[str, Any]) -> str:
    profile_id = str(row.get("ideCadastro", "")).strip()
    if profile_id:
        return f"camara:{profile_id}"
    # The bulk export also includes 12 party and government leadership payees.
    # They have a source transaction identifier but no deputy profile code.
    source_id = str(row.get("nuDeputadoId", "")).strip()
    if source_id:
        return f"camara:group:{source_id}"
    normalized = norm_name(row.get("txNomeParlamentar"))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"camara:group:{digest}"


def add_chamber_authority(
    authorities: dict[str, dict[str, Any]],
    authority_id: str,
    name: Any,
    state: Any,
    party: Any,
    source_id: str,
    source_url: str,
    *,
    prefer_existing: bool = False,
) -> None:
    if not authority_id:
        return
    institutional_account = authority_id.startswith("camara:group:")
    value = {
        "id": authority_id,
        "name": str(name or "").strip() or "Deputado sem nome informado",
        "role": "conta_institucional" if institutional_account else "deputado",
        "branch": "legislativo",
        "sphere": "federal",
        "institution": "Câmara dos Deputados",
        "uf": str(state or "").strip() or None,
        "party": str(party or "").strip() or None,
        "sourceId": source_id,
        "sourceUrl": source_url,
    }
    if institutional_account:
        value["position"] = "Conta de liderança partidária (não é pessoa)"
    if authority_id not in authorities or not prefer_existing:
        authorities[authority_id] = value
    else:
        current = authorities[authority_id]
        for key in ("name", "uf", "party"):
            if not current.get(key) and value.get(key):
                current[key] = value[key]


def load_chamber_expenses(path: Path, year: int, authorities: dict[str, dict[str, Any]], source_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expenses: list[dict[str, Any]] = []
    native_ids: list[str | None] = []
    row_index = 0
    document_ids_redacted = 0
    min_date: str | None = None
    max_date: str | None = None
    years: dict[str, int] = {}
    members: list[str] = []
    with zipfile.ZipFile(path) as archive:
        csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_members:
            raise ValueError("Official Câmara ZIP contains no CSV member")
        members = archive.namelist()
        for member_name in csv_members:
            with archive.open(member_name) as binary:
                text = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
                reader = csv.DictReader(text, delimiter=";")
                if not reader.fieldnames:
                    raise ValueError(f"CSV has no header: {member_name}")
                # Handles older exports whose first quoted field includes a BOM.
                reader.fieldnames = [str(field).lstrip("\ufeff\xef\xbb\xbf\"") for field in reader.fieldnames]
                for raw in reader:
                    row_index += 1
                    row = {
                        str(key).lstrip("\ufeff\xef\xbb\xbf\""): value
                        for key, value in raw.items()
                        if key is not None
                    }
                    authority_id = chamber_authority_id(row)
                    source_authority_url = CHAMBER_CEAP_URL.format(year=year)
                    add_chamber_authority(
                        authorities,
                        authority_id,
                        row.get("txNomeParlamentar"),
                        row.get("sgUF"),
                        row.get("sgPartido"),
                        source_id,
                        source_authority_url,
                        prefer_existing=True,
                    )
                    date = parse_date(row.get("datEmissao"))
                    min_date = min(min_date, date) if min_date and date else (date or min_date)
                    max_date = max(max_date, date) if max_date and date else (date or max_date)
                    source_year = int_or_none(row.get("numAno")) or year
                    source_month = int_or_none(row.get("numMes"))
                    years[str(source_year)] = years.get(str(source_year), 0) + 1
                    document_id = str(row.get("ideDocumento") or row.get("txtNumero") or "").strip() or None
                    if is_ambiguous_document_id(document_id):
                        document_id = None
                        document_ids_redacted += 1
                    native_id = str(row.get("ideDocumento") or "").strip() or None
                    expenses.append(
                        {
                            "id": "",
                            "authorityId": authority_id,
                            "sourceId": source_id,
                            "date": date,
                            "year": source_year,
                            "month": source_month,
                            "category": str(row.get("txtDescricao") or "").strip() or None,
                            "amount": parse_amount(row.get("vlrLiquido")),
                            "documentId": document_id,
                            "documentUrl": str(row.get("urlDocumento") or "").strip() or None,
                            "supplier": supplier_fields(
                                row.get("txtFornecedor"),
                                row.get("txtCNPJCPF"),
                                "camara",
                                row_index,
                            ),
                            "kind": HOUSING_COMPLEMENT_KIND
                            if str(row.get("txtDescricao") or "").strip() == HOUSING_COMPLEMENT_CATEGORY
                            else "reembolso",
                        }
                    )
                    native_ids.append(native_id)
    identity_stats = assign_stable_expense_ids(expenses, source_id, native_ids)
    return expenses, {
        "rows": row_index,
        "csvMembers": len([name for name in members if name.lower().endswith(".csv")]),
        "zipMembers": members,
        "dateMin": min_date,
        "dateMax": max_date,
        "expenseYears": years,
        "authorityIdsInFile": len({expense["authorityId"] for expense in expenses}),
        "deputyProfileIDs": len(
            {
                expense["authorityId"]
                for expense in expenses
                if not expense["authorityId"].startswith("camara:group:")
            }
        ),
        "institutionalAccounts": len(
            {
                expense["authorityId"]
                for expense in expenses
                if expense["authorityId"].startswith("camara:group:")
            }
        ),
        "negativeAmountRows": sum(1 for expense in expenses if expense["amount"] < 0),
        "documentIdsRedacted": document_ids_redacted,
        **identity_stats,
    }


def senate_exercise_status(item: ET.Element) -> str | None:
    """Describe the latest source interval without inferring present-day tenure."""
    exercises = item.findall("./Mandato/Exercicios/Exercicio")
    if not exercises:
        return None
    dated = [(parse_date(exercise.findtext("DataInicio")), exercise) for exercise in exercises]
    # An undated interval could be the latest one; do not guess from XML order.
    if any(start is None for start, _ in dated):
        return None
    latest_start = max(start for start, _ in dated)
    latest = [exercise for start, exercise in dated if start == latest_start]
    statuses = set()
    for exercise in latest:
        raw_end = (exercise.findtext("DataFim") or "").strip()
        end = parse_date(raw_end)
        if raw_end and (not end or end < latest_start):
            return None
        if end:
            status = f"Exercício de {date_br(latest_start)} a {date_br(end)}"
            reason = (exercise.findtext("DescricaoCausaAfastamento") or "").strip()
            if reason:
                status += f" — {reason}"
        else:
            status = f"Exercício sem término informado desde {date_br(latest_start)}"
        statuses.add(status)
    # Conflicting intervals with the same start do not establish one status.
    return statuses.pop() if len(statuses) == 1 else None


def senate_roster_detail(roster: list[dict[str, Any]], version: str | None) -> str:
    return (
        f"A lista oficial consultada contém {len(roster)} registros do Senado; "
        f"versão declarada pela fonte: {version or 'não informada'}. "
        "Registros não equivalem a cadeiras: a lista pode incluir suplentes em transição. "
        "Participação no mandato e último exercício são os publicados nessa fotografia; "
        "término ausente não confirma exercício na data de hoje."
    )


def senate_xml_authorities(content: bytes, source_id: str, source_url: str) -> tuple[list[dict[str, Any]], str | None]:
    root = ET.fromstring(content)
    metadata = root.find("Metadados")
    source_version = metadata.findtext("Versao") if metadata is not None else None
    rows: list[dict[str, Any]] = []
    for item in root.findall("./Parlamentares/Parlamentar"):
        info = item.find("IdentificacaoParlamentar")
        if info is None:
            continue
        code = (info.findtext("CodigoParlamentar") or "").strip()
        name = (info.findtext("NomeParlamentar") or "").strip()
        if not code or not name:
            continue
        rows.append(
            {
                "id": f"senado:{code}",
                "name": name,
                "role": "senador",
                "branch": "legislativo",
                "sphere": "federal",
                "institution": "Senado Federal",
                "uf": ((info.findtext("UfParlamentar") or "").strip()
                       or (item.findtext("Mandato/UfParlamentar") or "").strip() or None),
                "party": (info.findtext("SiglaPartidoParlamentar") or "").strip() or None,
                "position": (item.findtext("Mandato/DescricaoParticipacao") or "").strip() or None,
                "employmentStatus": senate_exercise_status(item),
                "sourceId": source_id,
                "sourceUrl": source_url,
            }
        )
    if not rows:
        raise ValueError("Official Senado roster contained no senators")
    return rows, source_version


def add_senate_expense_authorities(
    rows: list[dict[str, Any]],
    authorities: dict[str, dict[str, Any]],
    source_id: str,
    source_url: str,
) -> None:
    for row in rows:
        code = str(row.get("codSenador") or "").strip()
        if not code:
            continue
        authority_id = f"senado:{code}"
        authority = {
            "id": authority_id,
            "name": str(row.get("nomeSenador") or "").strip() or "Senador sem nome informado",
            "role": "senador",
            "branch": "legislativo",
            "sphere": "federal",
            "institution": "Senado Federal",
            "uf": None,
            "party": None,
            "sourceId": source_id,
            "sourceUrl": source_url,
        }
        if authority_id not in authorities:
            authorities[authority_id] = authority


def load_senate_expenses(path: Path, year: int, authorities: dict[str, dict[str, Any]], source_id: str, source_url: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Senate CEAPS endpoint did not return an array")
    rows = [row for row in payload if isinstance(row, dict)]
    add_senate_expense_authorities(rows, authorities, source_id, source_url)
    expenses: list[dict[str, Any]] = []
    native_ids: list[Any] = []
    document_ids_redacted = 0
    min_date: str | None = None
    max_date: str | None = None
    years: dict[str, int] = {}
    ids_seen: set[str] = set()
    for row_index, row in enumerate(rows, start=1):
        date = parse_date(row.get("data"))
        min_date = min(min_date, date) if min_date and date else (date or min_date)
        max_date = max(max_date, date) if max_date and date else (date or max_date)
        source_year = int_or_none(row.get("ano")) or year
        source_month = int_or_none(row.get("mes"))
        years[str(source_year)] = years.get(str(source_year), 0) + 1
        ids_seen.add(str(row.get("codSenador") or ""))
        document_id = str(row.get("documento") or "").strip() or None
        if is_ambiguous_document_id(document_id):
            document_id = None
            document_ids_redacted += 1
        expenses.append(
            {
                "id": "",
                "authorityId": f"senado:{row.get('codSenador')}",
                "sourceId": source_id,
                "date": date,
                "year": source_year,
                "month": source_month,
                "category": str(row.get("tipoDespesa") or "").strip() or None,
                "amount": parse_amount(row.get("valorReembolsado")),
                "documentId": document_id,
                "documentUrl": None,
                "supplier": supplier_fields(
                    row.get("fornecedor"),
                    row.get("cpfCnpj"),
                    "senado",
                    row_index,
                ),
                "kind": "reembolso",
                "airline": ticket_airline(row.get("detalhamento")),
            }
        )
        native_ids.append(row.get("id"))
    identity_stats = assign_stable_expense_ids(expenses, source_id, native_ids)
    return expenses, {
        "rows": len(rows),
        "dateMin": min_date,
        "dateMax": max_date,
        "expenseYears": years,
        "authorityIdsInFile": len(ids_seen - {""}),
        "negativeAmountRows": sum(1 for row in expenses if row["amount"] < 0),
        "documentIdsRedacted": document_ids_redacted,
        **identity_stats,
    }


def source_record(
    source_id: str,
    label: str,
    url: str,
    scope: str,
    period: str,
    status: str,
    detail: str,
    fetched_at: str,
    debug: str | None = None,
) -> dict[str, Any]:
    source = {
        "id": source_id,
        "label": label,
        "url": url,
        "scope": scope,
        "period": period,
        "status": status,
        "detail": detail,
        "fetchedAt": fetched_at,
    }
    if debug:
        source["debug"] = debug
    return source


def import_year(year: int, output: Path) -> dict[str, Any]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    sources: list[dict[str, Any]] = []
    authorities: dict[str, dict[str, Any]] = {}
    expenses: list[dict[str, Any]] = []
    current_year = dt.datetime.now(dt.timezone.utc).year

    chamber_url = CHAMBER_CEAP_URL.format(year=year)
    chamber_roster_rows: list[dict[str, Any]] = []
    chamber_roster_page_count = 0
    chamber_roster_status = "unavailable"
    chamber_roster_debug: str | None = None
    try:
        chamber_roster_rows, chamber_roster_page_count, _ = fetch_chamber_roster()
        for row in chamber_roster_rows:
            authority_id = f"camara:{row.get('id')}"
            add_chamber_authority(
                authorities,
                authority_id,
                row.get("nome"),
                row.get("siglaUf"),
                row.get("siglaPartido"),
                "camara_deputies_current",
                str(row.get("uri") or CHAMBER_DEPUTIES_URL),
            )
        chamber_roster_status = "imported"
        roster_detail = (
            f"A lista oficial de deputados em exercício foi percorrida por completo: "
            f"{len(chamber_roster_rows)} nomes em {chamber_roster_page_count} páginas da API."
        )
    except Exception as error:  # Keep other chamber data importable if this source fails.
        chamber_roster_debug = f"{type(error).__name__}: {error}"
        roster_detail = "Não foi possível consultar a lista atual de deputados da Câmara."
    sources.append(
        source_record(
            "camara_deputies_current",
            "Câmara dos Deputados: deputados em exercício",
            CHAMBER_DEPUTIES_URL,
            "Deputados que a API oficial da Câmara lista como atualmente em exercício.",
            "Lista em vigor na consulta",
            chamber_roster_status,
            roster_detail,
            utc_now(),
            chamber_roster_debug,
        )
    )

    chamber_path = RAW_DIR / f"camara-{year}.csv.zip"
    try:
        chamber_content = download(chamber_url, chamber_path)
        if not zipfile.is_zipfile(io.BytesIO(chamber_content)):
            raise ValueError("Câmara endpoint did not return a valid ZIP archive")
        chamber_expenses, chamber_stats = load_chamber_expenses(
            chamber_path, year, authorities, "camara_ceap"
        )
        expenses.extend(chamber_expenses)
        partial = year == current_year
        chamber_status = "partial" if partial else "imported"
        chamber_row_count = f"{chamber_stats['rows']:,}".replace(",", ".")
        detail = (
            f"Arquivo anual oficial processado por completo: {chamber_row_count} registros, "
            f"com datas de emissão de {date_br(chamber_stats['dateMin'])} a {date_br(chamber_stats['dateMax'])}. "
            f"O arquivo contém {chamber_stats['authorityIdsInFile']} IDs: "
            f"{chamber_stats['deputyProfileIDs']} perfis de deputados e "
            f"{chamber_stats['institutionalAccounts']} contas institucionais de liderança. "
            f"{chamber_stats['negativeAmountRows']} valores negativos foram mantidos com o sinal original "
            "(créditos/estornos, quando aplicável). "
            f"{chamber_stats['persistentIdRows']} lançamentos usam identificador documental exclusivo; "
            f"{chamber_stats['fingerprintRows']} usam ID derivado do conteúdo para preservar duplicatas "
            "idênticas sem identificador exclusivo."
        )
        if partial:
            detail += f" O ano de {year} ainda está em andamento; estes dados refletem o conteúdo disponível no arquivo consultado."
        if chamber_stats["fingerprintRows"]:
            detail += " Correções nesses lançamentos podem aparecer como novos registros, pois não há ID nativo exclusivo."
        if chamber_stats["documentIdsRedacted"]:
            detail += f" {chamber_stats['documentIdsRedacted']} referências documentais ambíguas de 11 dígitos foram omitidas."
    except Exception as error:
        chamber_status = "unavailable"
        detail = f"Não foi possível importar o arquivo oficial de despesas da CEAP de {year}."
        chamber_debug = f"{type(error).__name__}: {error}"
        chamber_stats = {}
    else:
        chamber_debug = None
    sources.append(
        source_record(
            "camara_ceap",
            "Câmara dos Deputados: despesas da cota parlamentar (CEAP)",
            chamber_url,
            "Despesas da CEAP incluídas no arquivo anual oficial da Câmara para o ano solicitado.",
            f"{year} (parcial, ano em andamento)" if year == current_year else str(year),
            chamber_status,
            detail,
            utc_now(),
            chamber_debug,
        )
    )

    senate_roster_url = SENATE_ROSTER_URL
    senate_roster_path = RAW_DIR / "senadores-atual.xml"
    try:
        senate_content = download(
            senate_roster_url, senate_roster_path, accept="application/xml"
        )
        senate_roster, senate_version = senate_xml_authorities(
            senate_content, "senado_senators_current", senate_roster_url
        )
        for authority in senate_roster:
            authorities[authority["id"]] = authority
        senate_roster_status = "imported"
        roster_detail = senate_roster_detail(senate_roster, senate_version)
        senate_roster_debug = None
    except Exception as error:
        senate_roster_status = "unavailable"
        roster_detail = "Não foi possível consultar a lista atual de senadores do Senado Federal."
        senate_roster_debug = f"{type(error).__name__}: {error}"
    sources.append(
        source_record(
            "senado_senators_current",
            "Senado Federal: senadores em exercício",
            senate_roster_url,
            "Senadores em exercício conforme a lista oficial do Senado Federal.",
            "Lista em vigor na consulta",
            senate_roster_status,
            roster_detail,
            utc_now(),
            senate_roster_debug,
        )
    )

    senate_url = SENATE_CEAPS_URL.format(year=year)
    senate_path = RAW_DIR / f"senado-{year}.json"
    try:
        senate_content = download(senate_url, senate_path)
        senate_expenses, senate_stats = load_senate_expenses(
            senate_path, year, authorities, "senado_ceaps", senate_url
        )
        expenses.extend(senate_expenses)
        partial = year == current_year
        senate_status = "partial" if partial else "imported"
        senate_row_count = f"{senate_stats['rows']:,}".replace(",", ".")
        detail = (
            f"O endpoint oficial retornou {senate_row_count} registros para a competência {year}; "
            f"as datas registradas vão de {date_br(senate_stats['dateMin'])} a {date_br(senate_stats['dateMax'])}. "
            f"{senate_stats['negativeAmountRows']} valores negativos foram mantidos com o sinal original "
            "(créditos/estornos, quando aplicável). "
            f"{senate_stats['persistentIdRows']} lançamentos usam ID nativo exclusivo; "
            f"{senate_stats['fingerprintRows']} usam ID derivado do conteúdo para preservar duplicatas "
            "idênticas sem identificador exclusivo."
        )
        if partial:
            detail += f" O ano de {year} ainda está em andamento; os dados refletem os registros disponibilizados pelo endpoint até a consulta."
        if senate_stats["fingerprintRows"]:
            detail += " Correções nesses lançamentos podem aparecer como novos registros, pois não há ID nativo exclusivo."
        if senate_stats["documentIdsRedacted"]:
            detail += f" {senate_stats['documentIdsRedacted']} referências documentais ambíguas de 11 dígitos foram omitidas."
        senate_debug = None
    except Exception as error:
        senate_status = "unavailable"
        detail = f"Não foi possível consultar as despesas CEAPS do ano de competência {year}."
        senate_debug = f"{type(error).__name__}: {error}"
        senate_stats = {}
    sources.append(
        source_record(
            "senado_ceaps",
            "Senado Federal: despesas da cota parlamentar (CEAPS)",
            senate_url,
            "Despesas CEAPS retornadas pelo endpoint oficial para o ano de competência solicitado.",
            f"{year} (parcial, ano em andamento)" if year == current_year else str(year),
            senate_status,
            detail,
            utc_now(),
            senate_debug,
        )
    )

    sanitize_expense_suppliers(expenses)

    # Current roster metadata takes precedence, while expense-only former
    # parliamentarians retain the name, UF and party supplied with their record.
    output_data = {
        "sources": sources,
        "authorities": list(authorities.values()),
        "expenses": expenses,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".tmp")
    with temp_output.open("w", encoding="utf-8") as stream:
        json.dump(output_data, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
    temp_output.replace(output)
    return output_data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True, help="Expense dataset year")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "imports" / "legislative.json",
        help="Output JSON path (default: data/imports/legislative.json)",
    )
    args = parser.parse_args(argv)
    if args.year < 2000 or args.year > dt.datetime.now(dt.timezone.utc).year:
        parser.error("--year must be between 2000 and the current year")
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = import_year(args.year, output)
    print(
        json.dumps(
            {
                "output": str(output),
                "sources": [
                    {"id": source["id"], "status": source["status"], "detail": source["detail"]}
                    for source in result["sources"]
                ],
                "authorities": len(result["authorities"]),
                "expenses": len(result["expenses"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    unavailable = [source for source in result["sources"] if source["status"] == "unavailable"]
    return 1 if unavailable else 0


if __name__ == "__main__":
    sys.exit(main())
