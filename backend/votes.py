"""Read the reviewed Câmara voting scoreboard snapshots."""
from __future__ import annotations

from datetime import date
import json
import re
import threading
from pathlib import Path

from .config import SNAPSHOTS_PATH
from .database import fold

INDEX_NAME = 'chamber-votes.json'
DETAILS_DIRECTORY = 'chamber-vote-details'
_VOTE_ID = re.compile(r'^\d+-\d+$')
_DETAILS_VERSION = re.compile(r'^[0-9a-f]{64}$')
_THEME_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
_PARTICIPANT_ID = re.compile(r'^camara:\d+$')
_VOTE_CHOICES = {'Sim', 'Não', 'Abstenção', 'Obstrução', 'Presidiu'}
_OUTCOMES = {'approved', 'rejected', 'not_approved'}
_ITEM_FIELDS = ('id', 'date', 'proposition', 'type', 'title', 'summary', 'decisionLabel',
                'yesMeaning', 'noMeaning', 'outcome', 'tally', 'themes', 'sources', 'reviewedAt')
_COVERAGE_FIELDS = ('inventoryCount', 'candidateCount', 'reviewedCount', 'publishedCount', 'pendingCount')
_OPTIONAL_COVERAGE_FIELDS = ('excludedCount', 'missingTextCount', 'missingAbstentionCount', 'missingThemeCount',
                             'segmentCount')
# Decisões sobre trechos (destaques e emendas) penduradas na votação do texto principal.
_SEGMENT_KINDS = {'destaque', 'emenda', 'emendas', 'emenda_redacao', 'dispositivos'}
_SEGMENT_OUTCOMES = {'approved', 'rejected', 'kept', 'removed'}

_cache_lock = threading.Lock()
_snapshot_cache: dict[Path, tuple[tuple[int, int], object]] = {}


def _reject_json_constant(value):
    raise ValueError(f'Constante JSON inválida: {value}')


def _load_json(path):
    """Load one snapshot, caching only while its resolved path and file stat match."""
    resolved = Path(path).expanduser().resolve()
    with _cache_lock:
        for _ in range(2):
            try:
                before = resolved.stat()
            except OSError:
                _snapshot_cache.pop(resolved, None)
                return None
            signature = (before.st_mtime_ns, before.st_size)
            cached = _snapshot_cache.get(resolved)
            if cached is not None and cached[0] == signature:
                return cached[1]
            try:
                value = json.loads(resolved.read_text(encoding='utf-8'), parse_constant=_reject_json_constant)
                after = resolved.stat()
            except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
                _snapshot_cache.pop(resolved, None)
                return None
            if signature == (after.st_mtime_ns, after.st_size):
                _snapshot_cache[resolved] = (signature, value)
                return value
        _snapshot_cache.pop(resolved, None)
        return None


def _text(value, *, limit=5000, required=True):
    return (isinstance(value, str) and len(value) <= limit and
            (not required or bool(value.strip())))


def _count(value, *, nullable=False):
    return ((nullable and value is None) or
            (isinstance(value, int) and not isinstance(value, bool) and value >= 0))


def _tally(value):
    if not isinstance(value, dict) or any(not _count(value.get(key), nullable=True)
                                          for key in ('yes', 'no', 'abstention', 'total')):
        return None
    return {key: value[key] for key in ('yes', 'no', 'abstention', 'total')}


def _https(value):
    return _text(value, limit=2048) and value.startswith('https://')


def _segment_item(value, parent_date):
    """Validate one reviewed decision about part of the text, voted on or after its main vote."""
    if (not isinstance(value, dict) or not _VOTE_ID.fullmatch(str(value.get('id', '')))
            or not _text(value.get('date'), limit=10) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['date'])
            or value['date'] < parent_date or value.get('kind') not in _SEGMENT_KINDS
            or value.get('outcome') not in _SEGMENT_OUTCOMES):
        return None
    for key, limit in (('title', 300), ('summary', 5000), ('decisionLabel', 300), ('yesMeaning', 500),
                       ('noMeaning', 500), ('reviewedAt', 80)):
        if not _text(value.get(key), limit=limit):
            return None
    tally, sources = _tally(value.get('tally')), value.get('sources')
    if tally is None or not isinstance(sources, dict) or any(not _https(sources.get(key))
                                                             for key in ('vote', 'rollCall', 'text', 'proposition')):
        return None
    notes = value.get('dataNotes')
    if 'dataNotes' in value and (not isinstance(notes, list) or len(notes) > 4
                                or any(not _text(note, limit=500) for note in notes)):
        return None
    return {**{key: value[key] for key in ('id', 'date', 'kind', 'title', 'summary', 'decisionLabel', 'yesMeaning',
                                           'noMeaning', 'outcome', 'reviewedAt')},
            'tally': tally, 'sources': {key: sources[key] for key in ('vote', 'rollCall', 'text', 'proposition')},
            **({'dataNotes': notes} if 'dataNotes' in value else {})}


def _summary_item(value):
    """Validate and project the public summary fields, excluding all detail-only data."""
    if not isinstance(value, dict) or not _VOTE_ID.fullmatch(str(value.get('id', ''))):
        return None
    if not _text(value.get('date'), limit=10):
        return None
    try:
        parsed_date = date.fromisoformat(value['date'])
    except ValueError:
        return None
    if parsed_date.isoformat() != value['date']:
        return None
    if value.get('type') not in {'PL', 'PLP', 'PEC'}:
        return None
    for key, limit in (('proposition', 100), ('title', 300), ('summary', 5000),
                       ('decisionLabel', 300), ('yesMeaning', 500), ('noMeaning', 500), ('reviewedAt', 80)):
        if not _text(value.get(key), limit=limit):
            return None
    if value.get('outcome') not in _OUTCOMES | {None}:
        return None

    tally = value.get('tally')
    if not isinstance(tally, dict) or any(not _count(tally.get(key), nullable=True)
                                          for key in ('yes', 'no', 'abstention', 'total')):
        return None
    themes = value.get('themes')
    if not isinstance(themes, list):
        return None
    safe_themes = []
    seen_themes = set()
    for theme in themes:
        if (not isinstance(theme, dict) or not isinstance(theme.get('id'), str)
                or not _THEME_ID.fullmatch(theme['id']) or not _text(theme.get('label'), limit=120)
                or theme['id'] in seen_themes):
            return None
        seen_themes.add(theme['id'])
        safe_themes.append({'id': theme['id'], 'label': theme['label']})
    sources = value.get('sources')
    if not isinstance(sources, dict):
        return None
    safe_sources = {}
    for key in ('vote', 'rollCall', 'proposition'):
        source = sources.get(key)
        if not _text(source, limit=2048) or not source.startswith('https://'):
            return None
        safe_sources[key] = source
    if 'text' not in sources:
        return None
    text_source = sources['text']
    if text_source is not None and (not _text(text_source, limit=2048) or not text_source.startswith('https://')):
        return None
    safe_sources['text'] = text_source
    decision_source = sources.get('decision')
    if 'decision' in sources:
        if decision_source is not None and (not _text(decision_source, limit=2048)
                                            or not decision_source.startswith('https://')):
            return None
        safe_sources['decision'] = decision_source
    if 'referenceProposition' in sources:
        reference = sources['referenceProposition']
        if not _text(reference, limit=2048) or not reference.startswith('https://'):
            return None
        safe_sources['referenceProposition'] = reference
    related = value.get('related')
    if 'related' in value and (
            not isinstance(related, dict) or not _VOTE_ID.fullmatch(str(related.get('id', '')))
            or related.get('relation') not in {'approvedAfter', 'rejectedBefore'}
            or related.get('outcome') not in _OUTCOMES or not isinstance(related.get('tally'), dict)
            or any(not _count(related['tally'].get(key), nullable=True) for key in ('yes', 'no', 'abstention', 'total'))):
        return None
    notes = value.get('dataNotes')
    if 'dataNotes' in value and (not isinstance(notes, list) or len(notes) > 4
                                or any(not _text(note, limit=500) for note in notes)):
        return None
    segments = value.get('segments')
    if 'segments' in value:
        if not isinstance(segments, list) or not segments:
            return None
        segments = [_segment_item(segment, value['date']) for segment in segments]
        if any(segment is None for segment in segments) or len({segment['id'] for segment in segments}) != len(segments):
            return None

    return {
        'id': value['id'], 'date': value['date'], 'proposition': value['proposition'], 'type': value['type'],
        'title': value['title'], 'summary': value['summary'], 'decisionLabel': value['decisionLabel'],
        'yesMeaning': value['yesMeaning'], 'noMeaning': value['noMeaning'], 'outcome': value['outcome'],
        'tally': {key: tally[key] for key in ('yes', 'no', 'abstention', 'total')},
        'themes': safe_themes, 'sources': safe_sources, 'reviewedAt': value['reviewedAt'],
        **({'dataNotes': notes} if 'dataNotes' in value else {}),
        **({'segments': segments} if 'segments' in value else {}),
        **({'related': {'id': related['id'], 'relation': related['relation'], 'outcome': related['outcome'],
                        'tally': {key: related['tally'][key] for key in ('yes', 'no', 'abstention', 'total')}}}
           if 'related' in value else {}),
    }


def _index(path=None):
    snapshot_path = Path(path) if path is not None else Path(SNAPSHOTS_PATH) / INDEX_NAME
    data = _load_json(snapshot_path)
    if not isinstance(data, dict) or data.get('schemaVersion') != 1:
        return None
    details_version = data.get('detailsVersion')
    if 'detailsVersion' in data and (not isinstance(details_version, str)
                                     or not _DETAILS_VERSION.fullmatch(details_version)):
        return None
    if not _text(data.get('generatedAt'), limit=80):
        return None
    period = data.get('period')
    if not isinstance(period, dict) or not all(_text(period.get(key), limit=10) for key in ('start', 'end')):
        return None
    try:
        start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
    except ValueError:
        return None
    if start.isoformat() != period['start'] or end.isoformat() != period['end'] or start > end:
        return None
    coverage = data.get('coverage')
    if not isinstance(coverage, dict) or any(not _count(coverage.get(key)) for key in _COVERAGE_FIELDS):
        return None
    if any(key in coverage and not _count(coverage[key]) for key in _OPTIONAL_COVERAGE_FIELDS):
        return None
    if any(key in coverage and coverage[key] > coverage['publishedCount']
           for key in ('missingTextCount', 'missingAbstentionCount', 'missingThemeCount')):
        return None
    if ('excludedCount' in coverage
            and (coverage['publishedCount'] + coverage['excludedCount'] + coverage['pendingCount']
                 != coverage['candidateCount']
                 or coverage['publishedCount'] + coverage['excludedCount'] > coverage['reviewedCount']
                 or coverage['reviewedCount'] > coverage['candidateCount'])):
        return None
    if not _text(coverage.get('detail'), limit=3000, required=False):
        return None
    items = data.get('items')
    if not isinstance(items, list):
        return None
    safe_items = []
    seen_ids = set()
    for raw_item in items:
        item = _summary_item(raw_item)
        if item is None:
            return None
        ids = [item['id'], *(segment['id'] for segment in item.get('segments', []))]
        if len(set(ids)) != len(ids) or any(identifier in seen_ids for identifier in ids):
            return None
        seen_ids.update(ids)
        safe_items.append(item)
    if coverage.get('segmentCount', 0) != sum(len(item.get('segments', [])) for item in safe_items):
        return None
    if coverage['publishedCount'] != len(safe_items):
        return None
    # Latest decisions first; IDs make same-day ordering stable.
    safe_items.sort(key=lambda item: item['id'])
    safe_items.sort(key=lambda item: item['date'], reverse=True)
    return {
        'generatedAt': data['generatedAt'], 'period': {'start': period['start'], 'end': period['end']},
        'coverage': {**{key: coverage[key] for key in (*_COVERAGE_FIELDS, *_OPTIONAL_COVERAGE_FIELDS)
                       if key in coverage}, 'detail': coverage['detail']},
        'items': safe_items, 'detailsVersion': details_version,
    }


def _page_number(value, default, upper=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 1:
        return 1
    return min(number, upper) if upper is not None else number


def listing(params=None, path=None):
    """Return filtered and paginated reviewed votes from the index snapshot."""
    params = params or {}
    snapshot = _index(path)
    page = _page_number(params.get('page', '1'), 1)
    page_size = _page_number(params.get('pageSize', '12'), 12, 24)
    if snapshot is None:
        return {'available': False, 'items': [], 'total': 0, 'page': page, 'pageSize': page_size,
                'pageCount': 0, 'period': None, 'coverage': None,
                'filters': {'types': [], 'themes': []}, 'generatedAt': None}

    all_items = snapshot['items']
    types = ['PL', 'PLP', 'PEC']
    themes_by_id = {}
    for item in all_items:
        for theme in item['themes']:
            themes_by_id.setdefault(theme['id'], theme)
    query = fold(str(params.get('q', ''))[:120]).strip()
    type_filter = str(params.get('type', '')).upper()
    theme_filter = str(params.get('theme', ''))
    # "not_approved" reúne rejeição explícita e falta de aprovação; valores desconhecidos são ignorados.
    result_filter = {'approved': {'approved'}, 'not_approved': {'rejected', 'not_approved'}}.get(
        str(params.get('result', '')))
    filtered = [item for item in all_items
                if (not query or all(word in fold(f"{item['title']} {item['summary']} {item['proposition']}")
                                     for word in query.split()))
                and (not type_filter or item['type'] == type_filter)
                and (not theme_filter or any(theme['id'] == theme_filter for theme in item['themes']))
                and (not result_filter or item['outcome'] in result_filter)]
    total = len(filtered)
    page_count = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size
    # A lista mostra só quantas decisões sobre trechos cada votação tem; o conteúdo fica no detalhe.
    page_items = [{**{key: value for key, value in item.items() if key != 'segments'},
                   **({'segmentCount': len(item['segments'])} if item.get('segments') else {})}
                  for item in filtered[offset:offset + page_size]]
    return {'available': True, 'items': page_items, 'total': total,
            'page': page, 'pageSize': page_size, 'pageCount': page_count,
            'period': snapshot['period'], 'coverage': snapshot['coverage'],
            'filters': {'types': types, 'themes': sorted(themes_by_id.values(), key=lambda theme: (theme['label'], theme['id']))},
            'generatedAt': snapshot['generatedAt']}


def _vote_details(snapshot_path, snapshot, identifier):
    """Load one validated roll-call detail file; invalid or absent files return no rows."""
    details_root = (snapshot_path.parent / DETAILS_DIRECTORY).resolve()
    details_version = snapshot['detailsVersion']
    details_directory = (details_root / details_version).resolve() if details_version else details_root
    details_path = (details_directory / f'{identifier}.json').resolve()
    # Keep detail file reads within the selected generation, including when local symlinks exist.
    directory_escaped = (details_version is not None and
                         (details_directory.parent != details_root or details_directory.name != details_version))
    if directory_escaped or details_path.parent != details_directory:
        details = None
    else:
        details = _load_json(details_path)
    participants, party_totals, available = [], [], False
    if isinstance(details, dict) and details.get('id') == identifier:
        raw_participants, raw_party_totals = details.get('participants'), details.get('partyTotals')
        valid_participants = isinstance(raw_participants, list)
        safe_participants = []
        seen_participants = set()
        if valid_participants:
            for participant in raw_participants:
                if (not isinstance(participant, dict) or not isinstance(participant.get('id'), str)
                        or not _PARTICIPANT_ID.fullmatch(participant['id'])
                        or participant['id'] in seen_participants
                        or not _text(participant.get('name'), limit=200)
                        or not _text(participant.get('party'), limit=80, required=False)
                        or not _text(participant.get('uf'), limit=2)
                        or not re.fullmatch(r'[A-Z]{2}', participant['uf'])
                        or participant.get('vote') not in _VOTE_CHOICES):
                    valid_participants = False
                    break
                seen_participants.add(participant['id'])
                safe_participants.append({key: participant[key] for key in ('id', 'name', 'party', 'uf', 'vote')})
        valid_party_totals = isinstance(raw_party_totals, list)
        safe_party_totals = []
        seen_parties = set()
        if valid_party_totals:
            for total in raw_party_totals:
                if (not isinstance(total, dict) or not _text(total.get('party'), limit=80, required=False)
                        or total['party'] in seen_parties
                        or any(not _count(total.get(key)) for key in ('yes', 'no', 'other'))):
                    valid_party_totals = False
                    break
                seen_parties.add(total['party'])
                safe_party_totals.append({key: total[key] for key in ('party', 'yes', 'no', 'other')})
        if valid_participants and valid_party_totals:
            participants, party_totals, available = safe_participants, safe_party_totals, True
    return participants, party_totals, available


def detail(identifier, path=None):
    """Return one reviewed summary and its optional local roll-call details."""
    if not isinstance(identifier, str) or not _VOTE_ID.fullmatch(identifier):
        return None
    snapshot_path = Path(path) if path is not None else Path(SNAPSHOTS_PATH) / INDEX_NAME
    snapshot = _index(snapshot_path)
    if snapshot is None:
        return None
    vote = next((item for item in snapshot['items'] if item['id'] == identifier), None)
    if vote is None:
        # Decisão sobre um trecho: mesma página, com a proposição e o link da votação principal.
        parent = next((item for item in snapshot['items']
                       if any(segment['id'] == identifier for segment in item.get('segments', []))), None)
        if parent is None:
            return None
        segment = next(segment for segment in parent['segments'] if segment['id'] == identifier)
        vote = {**segment, 'proposition': parent['proposition'], 'type': parent['type'], 'themes': parent['themes'],
                'parent': {'id': parent['id'], 'title': parent['title'], 'outcome': parent['outcome']}}

    participants, party_totals, available = _vote_details(snapshot_path, snapshot, identifier)
    return {'available': True, 'vote': vote, 'participants': participants,
            'partyTotals': party_totals, 'participantsAvailable': available}


# Siglas truncadas ou com grafia diferente na fonte, unificadas pela forma da lista atual.
_PARTY_ALIASES = {'REPUBLICAN': 'REPUBLICANOS', 'SOLIDARIED': 'SOLIDARIEDADE', 'PODEMOS': 'PODE'}


def party_key(party):
    """Normalize a published party label for comparisons between votes."""
    key = str(party or '').strip().upper()
    return _PARTY_ALIASES.get(key, key)


def party_totals(path=None):
    """Return each reviewed vote with Yes/No/other totals by published party.

    Votes without a valid detail file stay listed with ``partyTotals`` set to None,
    so a missing file never becomes a zero count.
    """
    snapshot_path = Path(path) if path is not None else Path(SNAPSHOTS_PATH) / INDEX_NAME
    snapshot = _index(snapshot_path)
    if snapshot is None:
        return {'available': False, 'items': [], 'period': None, 'coverage': None, 'generatedAt': None}
    items = []
    for vote in snapshot['items']:
        _, totals, available = _vote_details(snapshot_path, snapshot, vote['id'])
        by_party = None
        if available:
            by_party = {}
            for total in totals:
                key = party_key(total['party'])
                if not key:
                    continue
                merged = by_party.setdefault(key, {'yes': 0, 'no': 0, 'other': 0})
                for field in ('yes', 'no', 'other'):
                    merged[field] += total[field]
        items.append({key: vote[key] for key in ('id', 'date', 'proposition', 'type', 'title', 'outcome')}
                     | {'partyTotals': by_party})
    return {'available': True, 'items': items, 'period': snapshot['period'],
            'coverage': snapshot['coverage'], 'generatedAt': snapshot['generatedAt']}


_person_index_lock = threading.Lock()
_person_index_cache: dict[tuple, dict] = {}


def _person_index(snapshot_path, snapshot):
    """Map each deputy to their recorded choice per reviewed vote, built once per index generation."""
    stat = snapshot_path.stat()
    key = (str(snapshot_path.resolve()), stat.st_mtime_ns, stat.st_size, snapshot['detailsVersion'])
    with _person_index_lock:
        cached = _person_index_cache.get(key)
        if cached is not None:
            return cached
    by_person, missing_details = {}, set()
    # Pares de deputados(as) com voto registrado na mesma votação e quantos deles votaram igual:
    # a referência "dois deputados quaisquer" da comparação, no mesmo critério do cartão.
    pairs = agreeing_pairs = 0
    for vote in snapshot['items']:
        participants, _, available = _vote_details(snapshot_path, snapshot, vote['id'])
        if not available:
            missing_details.add(vote['id'])
            continue
        choices = {}
        for participant in participants:
            by_person.setdefault(participant['id'], {})[vote['id']] = participant['vote']
            if participant['vote'] is not None:
                choices[participant['vote']] = choices.get(participant['vote'], 0) + 1
        voters = sum(choices.values())
        pairs += voters * (voters - 1) // 2
        agreeing_pairs += sum(count * (count - 1) // 2 for count in choices.values())
    index = {'byPerson': by_person, 'missingDetails': missing_details,
             'pairAgreement': round(agreeing_pairs / pairs, 4) if pairs else None}
    with _person_index_lock:
        _person_index_cache.clear()
        _person_index_cache[key] = index
    return index


def person_votes(identifier, path=None):
    """Return every reviewed vote with this deputy's recorded choice.

    ``vote`` is None when the roll call has no row for the person (absent from the
    source, not in office) and ``detailsAvailable`` is False when the vote's detail
    file is missing; neither case is a "no" vote or an absence.
    """
    if not isinstance(identifier, str) or not _PARTICIPANT_ID.fullmatch(identifier):
        return None
    snapshot_path = Path(path) if path is not None else Path(SNAPSHOTS_PATH) / INDEX_NAME
    snapshot = _index(snapshot_path)
    if snapshot is None:
        return {'available': False, 'items': [], 'period': None, 'coverage': None, 'generatedAt': None}
    index = _person_index(snapshot_path, snapshot)
    choices = index['byPerson'].get(identifier, {})
    items = [{key: vote[key] for key in ('id', 'date', 'proposition', 'type', 'title', 'outcome')}
             | {'vote': choices.get(vote['id']), 'detailsAvailable': vote['id'] not in index['missingDetails']}
             for vote in snapshot['items']]
    return {'available': True, 'items': items, 'period': snapshot['period'],
            'coverage': snapshot['coverage'], 'generatedAt': snapshot['generatedAt'],
            'pairAgreement': index['pairAgreement']}
