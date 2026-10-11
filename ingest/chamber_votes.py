"""Build the reviewed voting catalogue and separate roll-call snapshots.

Reviews are local editorial inputs, never an automatic publication decision.
Offline by default; downloads and source checksums stay under data/.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from urllib.parse import urlsplit

from ingest.chamber_vote_inventory import API_BASE, ROOT, CollectionError, _load, _paged
from ingest.chamber_vote_rules import _recorded_partial_tally, classify_vote
from ingest.chamber_vote_segments import build_segments
from ingest.chamber_vote_report import identify_participants, parse_roll_call
from ingest.project_status import _atomic_bytes, _json_bytes, _valid_date, request_bytes, utc_now

VOTE_ID = re.compile(r'[0-9]+-[0-9]+')
CHOICES = {'Sim': 'Sim', 'Não': 'Não', 'Abstenção': 'Abstenção',
           'Obstrução': 'Obstrução', 'Artigo 17': 'Presidiu', 'Presidiu': 'Presidiu'}
REVIEW_FIELDS = ('title', 'summary', 'decisionLabel', 'yesMeaning', 'noMeaning')
PROPOSITION_LABEL = re.compile(r'(PL|PLP|PEC) ([1-9][0-9]*)/([0-9]{4})')
FICHA = 'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={}'
# Em 2023 a API registra a votação alguns minutos após o encerramento do relatório.
REGISTRATION_LAG = timedelta(minutes=5)


def _registered_after_report(report_end, registered):
    try:
        ended = datetime.fromisoformat(report_end)
        recorded = datetime.fromisoformat(str(registered))
    except (TypeError, ValueError):
        return False
    return timedelta(0) <= recorded.replace(second=0, microsecond=0) - ended <= REGISTRATION_LAG


def _valid_review_date(value):
    if _valid_date(value):
        return True
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _official_source(value, *, nullable=False):
    if nullable and value is None:
        return None
    parts = urlsplit(value) if isinstance(value, str) else None
    if (parts is None or parts.scheme != 'https' or parts.hostname not in
            {'www.camara.leg.br', 'www2.camara.leg.br', 'camara.leg.br',
             'dadosabertos.camara.leg.br', 'escriba.camara.leg.br'}
            or parts.username or parts.password or parts.port not in (None, 443)):
        raise CollectionError('A revisão precisa de um link oficial da Câmara.')
    return value


def _source_bytes(url, path, *, collect, refresh, request):
    """Cache a non-JSON official source with the same provenance as API caches."""
    previous = None
    try:
        content = path.read_bytes()
        metadata = json.loads(path.with_suffix('.meta.json').read_text())
        if (metadata.get('sourceUrl') == url and _valid_date(metadata.get('consultadoEm'))
                and metadata.get('sha256') == hashlib.sha256(content).hexdigest()
                and _nominal_report(content)):
            previous = (content, metadata)
    except (OSError, ValueError, AttributeError):
        pass
    if previous and not refresh:
        return previous
    if not collect:
        if previous:
            return previous
        raise CollectionError(f'{url}: fonte nominal ainda não coletada.')
    try:
        content = request(url)
    except (OSError, TimeoutError) as error:
        raise CollectionError(f'{url}: falha na fonte nominal; saída anterior preservada.') from error
    if not content:
        raise CollectionError(f'{url}: fonte nominal vazia.')
    if not _nominal_report(content):
        raise CollectionError(f'{url}: relatório não confirma método nominal eletrônico; fonte anterior preservada.')
    metadata = {'sourceUrl': url, 'consultadoEm': utc_now(),
                'sha256': hashlib.sha256(content).hexdigest()}
    _atomic_bytes(path, content)
    _atomic_bytes(path.with_suffix('.meta.json'), _json_bytes(metadata))
    return content, metadata


def _nominal_report(content):
    for encoding in ('utf-8', 'latin-1'):
        text = unescape(content.decode(encoding, errors='replace'))
        text = re.sub(r'<[^>]+>', ' ', text)
        text = ''.join(character for character in unicodedata.normalize('NFKD', text)
                       if not unicodedata.combining(character)).casefold()
        if re.search(r'nominal\s+eletronica', text):
            return True
    return False


def normalize_participants(rows, tally):
    people = {}
    for row in rows:
        person = row.get('deputado_')
        identifier = str(person.get('id', '')) if isinstance(person, dict) else ''
        choice = CHOICES.get(str(row.get('tipoVoto', '')).strip())
        if (not identifier.isdigit() or not choice or not person.get('nome')
                or not re.fullmatch(r'[A-Z]{2}', str(person.get('siglaUf', '')))):
            raise CollectionError('Voto individual sem pessoa, UF ou escolha reconhecida.')
        participant = {'id': f'camara:{identifier}', 'name': person['nome'],
                       'party': person.get('siglaPartido') or '', 'uf': person['siglaUf'], 'vote': choice}
        if identifier in people and people[identifier] != participant:
            raise CollectionError('Votos individuais duplicados conflitantes.')
        people[identifier] = participant
    counts = Counter(person['vote'] for person in people.values())
    for key, choice in (('yes', 'Sim'), ('no', 'Não'), ('abstention', 'Abstenção')):
        if tally.get(key) is not None and counts[choice] != tally[key]:
            raise CollectionError(f'Placar divergente dos votos individuais: {key}.')
    if tally.get('total') is not None and sum(counts[choice] for choice in ('Sim', 'Não', 'Abstenção')) != tally['total']:
        raise CollectionError('Total do placar divergente dos votos individuais.')
    if not people:
        raise CollectionError('A lista nominal está vazia.')
    parties = defaultdict(lambda: {'yes': 0, 'no': 0, 'other': 0})
    for participant in people.values():
        key = {'Sim': 'yes', 'Não': 'no'}.get(participant['vote'], 'other')
        parties[participant['party']][key] += 1
    return (sorted(people.values(), key=lambda person: (person['name'].casefold(), person['id'])),
            [{'party': party, **counts} for party, counts in sorted(parties.items())])


def build_catalogue(inventory, reviews, *, root=ROOT, collect=False, refresh=False, request=request_bytes,
                    segment_reviews=None):
    if not isinstance(inventory, dict) or inventory.get('listComplete') is not True:
        raise CollectionError('O catálogo exige o inventário completo da API.')
    if not isinstance(reviews, list):
        raise CollectionError('A revisão deve ser uma lista.')
    period = inventory['period']
    start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
    cache = root / 'data' / 'raw' / 'chamber-vote-inventory' / f'{start}_{end}'
    entries = {entry['id']: entry for entry in inventory['entries']}
    items, details, reviewed_ids, excluded_ids = [], {}, set(), set()
    registered, followers = {}, {}
    for review in reviews:
        identifier = review.get('id') if isinstance(review, dict) else None
        if not isinstance(identifier, str) or not VOTE_ID.fullmatch(identifier) or identifier in reviewed_ids:
            raise CollectionError('Revisão sem ID válido ou com ID duplicado.')
        entry = entries.get(identifier)
        if entry is None or not entry.get('candidate'):
            raise CollectionError(f'{identifier}: decisão fora dos candidatos do inventário.')
        reviewed_ids.add(identifier)
        if review.get('status') == 'pending':
            if not review.get('reason'):
                raise CollectionError(f'{identifier}: pendência sem motivo.')
            continue
        if review.get('status') == 'excluded':
            sources, evidence = review.get('sources'), review.get('evidence')
            if (not isinstance(review.get('reason'), str) or not review['reason'].strip()
                    or not _valid_review_date(review.get('reviewedAt'))
                    or not isinstance(sources, dict) or not sources
                    or not isinstance(evidence, dict)
                    or not any(isinstance(value, str) and value.strip() for value in evidence.values())):
                raise CollectionError(f'{identifier}: exclusão sem motivo, data, fonte e evidência.')
            for source in sources.values():
                _official_source(source)
            excluded_ids.add(identifier)
            continue
        if (review.get('status') != 'confirmed' or not review.get('reviewedAt')
                or any(not isinstance(review.get(field), str) or not review[field].strip() for field in REVIEW_FIELDS)
                or not isinstance(review.get('evidence'), dict)
                or any(not review['evidence'].get(field) for field in ('method', 'object', 'text'))):
            raise CollectionError(f'{identifier}: revisão incompleta.')
        sources = review.get('sources', {})
        safe_sources = {key: _official_source(sources.get(key), nullable=key == 'text')
                        for key in ('rollCall', 'text', 'decision', 'proposition')}
        url = f'{API_BASE}/votacoes/{identifier}'
        payload, detail_source = _load(url, cache / 'details' / f'{identifier}.json',
                                      collect=collect, refresh=refresh, request=request, detail=True)
        record = payload['dados']
        classification = classify_vote(record)
        targets, tally = classification['targetPropositions'], classification['recordedTally']
        if (record.get('id') != identifier or record.get('data') != entry['date']
                or not classification['candidate'] or len(targets) != 1):
            raise CollectionError(f'{identifier}: detalhe não confirma decisão, objeto de referência e placar.')
        target = targets[0]
        api_label = f'{target["siglaTipo"]} {target["numero"]}/{target["ano"]}'
        voted = review.get('votedProposition')
        if voted is not None:
            label = voted.get('label') if isinstance(voted, dict) else None
            voted_id = voted.get('id') if isinstance(voted, dict) else None
            match = PROPOSITION_LABEL.fullmatch(label) if isinstance(label, str) else None
            if (not match or not isinstance(voted_id, int) or isinstance(voted_id, bool) or voted_id <= 0
                    or label == api_label):
                raise CollectionError(f'{identifier}: proposição votada inválida ou igual à referência da API.')
            voted_type, voted_number, voted_year = match.group(1), int(match.group(2)), int(match.group(3))
        else:
            voted_id, label = target['id'], api_label
            voted_type, voted_number, voted_year = target['siglaTipo'], target['numero'], target['ano']
        expected_proposition = FICHA.format(voted_id)
        if safe_sources['proposition'] != expected_proposition:
            raise CollectionError(f'{identifier}: ficha da revisão não corresponde à proposição de referência.')
        content, report_source = _source_bytes(safe_sources['rollCall'], cache / 'reports' / f'{identifier}.html',
                                               collect=collect, refresh=refresh, request=request)
        if not _nominal_report(content):
            raise CollectionError(f'{identifier}: relatório não confirma método nominal eletrônico.')
        tally_source = review.get('tallySource', 'api')
        participants_source = review.get('participantsSource', 'api')
        if tally_source not in ('api', 'rollCall') or participants_source not in ('api', 'rollCall'):
            raise CollectionError(f'{identifier}: origem do placar ou dos votos individuais inválida.')
        report, data_notes = None, []
        if 'rollCall' in (tally_source, participants_source) or voted is not None:
            report = parse_roll_call(content)
            if (report['date'] != entry['date']
                    or report['proposition'] != {'type': voted_type, 'number': voted_number, 'year': voted_year}
                    or ('rollCall' in (tally_source, participants_source)
                        and report['object'] != review.get('reportObject'))
                    # Sem lista da API, só o horário liga o relatório à votação; com ela, a
                    # conciliação nominal abaixo confirma o vínculo.
                    or (participants_source == 'rollCall'
                        and not _registered_after_report(report['endedAt'], record.get('dataHoraRegistro')))):
                raise CollectionError(f'{identifier}: relatório não corresponde à data, objeto e horário da decisão.')
        if voted is not None:
            if voted_id == target['id']:
                data_notes.append(f'Os Dados Abertos mostram esta proposição com a numeração atual {api_label}. '
                                  f'O relatório nominal usa {label}, a numeração na data da votação.')
            else:
                proposition_record, _ = _load(f'{API_BASE}/proposicoes/{voted_id}',
                                              cache / 'propositions' / f'{voted_id}.json',
                                              collect=collect, refresh=refresh, request=request, detail=True)
                found = proposition_record['dados']
                if (found.get('id') != voted_id or found.get('siglaTipo') != voted_type
                        or found.get('numero') != voted_number or found.get('ano') != voted_year):
                    raise CollectionError(f'{identifier}: ficha oficial não confirma a proposição votada.')
                data_notes.append(f'Os Dados Abertos registram esta votação na proposição {api_label}. '
                                  f'O relatório nominal identifica a proposição votada como {label}.')
        if tally_source == 'rollCall':
            api_tally = _recorded_partial_tally(record.get('descricao'))
            obstructions = sum(row['vote'] == 'Obstrução' for row in report['participants'])
            if (obstructions and api_tally.get('total') is not None
                    and api_tally['total'] == report['tally']['total'] + obstructions):
                # O placar exclui obstrução do total; a descrição da API às vezes a inclui.
                api_tally = {**api_tally, 'total': None}
                counted = f'{obstructions} {"obstrução" if obstructions == 1 else "obstruções"}'
                data_notes.append(f'O total da descrição da API inclui {counted}. O Placar usa '
                                  'o total do relatório nominal, com Sim, Não e Abstenção.')
            for key, value in api_tally.items():
                if value is not None and report['tally'].get(key) is not None and value != report['tally'][key]:
                    raise CollectionError(f'{identifier}: placar da API diverge do relatório nominal.')
            tally = {key: value if value is not None else report['tally'][key]
                     for key, value in api_tally.items()}
        if not tally or tally['yes'] is None or tally['no'] is None:
            raise CollectionError(f'{identifier}: placar nominal não conferido.')
        rows, participant_sources = _paged(f'{url}/votos', cache / 'participants' / identifier,
                                           collect=collect, refresh=refresh, request=request)
        identity_sources = []
        participants_origin = 'api'
        if not rows and participants_source == 'rollCall':
            deputies, identity_sources = _paged(
                f'{API_BASE}/deputados?dataInicio={entry["date"]}&dataFim={entry["date"]}&itens=100',
                cache / 'deputies' / entry['date'], collect=collect, refresh=refresh, request=request)
            rows = identify_participants(report['participants'], deputies)
            participants_origin = 'rollCall'
            data_notes.append('Os votos individuais vêm do relatório nominal oficial. A lista '
                              'disponibilizada pelos Dados Abertos está vazia nesta decisão.')
        if tally_source == 'rollCall':
            data_notes.append('O placar foi conferido no relatório nominal oficial.')
        participants, party_totals = normalize_participants(rows, tally)
        theme_rows, theme_sources = _paged(f'{API_BASE}/proposicoes/{voted_id}/temas',
                                           cache / 'themes' / str(voted_id),
                                           collect=collect, refresh=refresh, request=request)
        themes = {}
        for theme in theme_rows:
            if (not isinstance(theme.get('codTema'), int) or isinstance(theme['codTema'], bool)
                    or not isinstance(theme.get('tema'), str) or not theme['tema'].strip()):
                raise CollectionError(f'{identifier}: tema oficial inválido.')
            theme_id = f'chamber-theme-{theme["codTema"]}'
            if theme_id in themes and themes[theme_id]['label'] != theme['tema']:
                raise CollectionError(f'{identifier}: tema oficial conflitante.')
            themes[theme_id] = {'id': theme_id, 'label': theme['tema']}
        outcome = 'approved' if record.get('aprovacao') == 1 else 'not_approved' if record.get('aprovacao') == 0 else None
        # Rejection is stated only after explicit review of the result.
        if outcome == 'not_approved' and review.get('outcome') == 'rejected':
            outcome = 'rejected'
        items.append({'id': identifier, 'date': entry['date'],
                      'proposition': label, 'type': voted_type, **{field: review[field] for field in REVIEW_FIELDS},
                      'outcome': outcome, 'tally': tally, 'themes': list(themes.values()),
                      'sources': {'vote': url, **safe_sources,
                                  **({'referenceProposition': FICHA.format(target['id'])}
                                     if voted_id != target['id'] else {})}, 'reviewedAt': review['reviewedAt'],
                      **({'dataNotes': data_notes} if data_notes else {})})
        registered[identifier] = str(record.get('dataHoraRegistro', ''))
        if review.get('followedBy') is not None:
            followers[identifier] = review['followedBy']
        details[identifier] = {'id': identifier, 'participants': participants, 'partyTotals': party_totals,
                               'sourceMetadata': {'vote': detail_source, 'rollCall': report_source,
                                                  'participants': participant_sources, 'themes': theme_sources,
                                                  **({'participantsOrigin': participants_origin,
                                                      'identities': identity_sources}
                                                     if participants_origin == 'rollCall' else {})}}
    _link_followed_versions(items, followers, registered)
    if segment_reviews is not None:
        details.update(build_segments(items, entries, segment_reviews, cache=cache,
                                      collect=collect, refresh=refresh, request=request))
    items.sort(key=lambda item: (item['date'], item['id']), reverse=True)
    published = len(items)
    excluded = len(excluded_ids)
    pending = inventory['candidateCount'] - published - excluded
    missing_text = sum(item['sources']['text'] is None for item in items)
    missing_abstention = sum(item['tally']['abstention'] is None for item in items)
    missing_theme = sum(not item['themes'] for item in items)
    coverage = {'inventoryCount': inventory['voteCount'], 'candidateCount': inventory['candidateCount'],
                'reviewedCount': len(reviewed_ids), 'publishedCount': published,
                'excludedCount': excluded, 'pendingCount': pending,
                'missingTextCount': missing_text, 'missingAbstentionCount': missing_abstention,
                'missingThemeCount': missing_theme,
                'segmentCount': sum(len(item.get('segments', [])) for item in items)}
    coverage['detail'] = _coverage_detail(coverage, str(start.year))
    details_version = hashlib.sha256(_json_bytes(details)).hexdigest()
    return {'schemaVersion': 1, 'generatedAt': utc_now(), 'period': period, 'detailsVersion': details_version,
            'coverage': coverage, 'items': items}, details


def _link_followed_versions(items, followers, registered):
    """Liga a versão rejeitada à decisão seguinte sobre a mesma proposição, na mesma data."""
    by_id = {item['id']: item for item in items}
    for identifier, following in followers.items():
        rejected, approved = by_id[identifier], by_id.get(following)
        if (approved is None or rejected['outcome'] not in ('rejected', 'not_approved')
                or approved['outcome'] != 'approved' or approved['proposition'] != rejected['proposition']
                or approved['date'] != rejected['date'] or not registered[identifier] < registered[following]):
            raise CollectionError(f'{identifier}: decisão seguinte não confirma aprovação posterior da mesma proposição.')
        rejected['related'] = {'id': following, 'relation': 'approvedAfter',
                               'outcome': approved['outcome'], 'tally': approved['tally']}
        approved['related'] = {'id': identifier, 'relation': 'rejectedBefore',
                               'outcome': rejected['outcome'], 'tally': rejected['tally']}


def _coverage_detail(coverage, label):
    return (f'{coverage["publishedCount"]} decisões nominais conferidas de {coverage["candidateCount"]} candidatos '
            f'provisórios em {coverage["inventoryCount"]} registros da API. Recorte de {label}: texto principal '
            f'de PL, PLP e PEC no Plenário da Câmara. {coverage["excludedCount"]} candidatos excluídos após revisão '
            f'com motivo e fonte; {coverage["pendingCount"]} ainda pendentes, incluindo os não revisados. '
            f'Decisões com lacunas: {coverage["missingTextCount"]} sem link seguro ao texto exato; '
            f'{coverage["missingAbstentionCount"]} sem contagem publicada de abstenções nas fontes usadas; '
            f'{coverage["missingThemeCount"]} sem tema oficial. '
            'O catálogo ainda não cobre todo o mandato. Temas da Câmara descrevem a proposição '
            'de referência. Campo ausente não significa zero. O resultado é o desta decisão, '
            'não a situação legal atual do projeto.')


def merge_catalogues(parts):
    """Join contiguous yearly catalogues into one index; each year keeps its own inventory and review."""
    if not parts:
        raise CollectionError('Nenhum período informado para o catálogo.')
    parts = sorted(parts, key=lambda part: part[0]['period']['start'])
    for (previous, _), (current, _) in zip(parts, parts[1:]):
        end = date.fromisoformat(previous['period']['end'])
        start = date.fromisoformat(current['period']['start'])
        if start.year != end.year + 1 or end != date(end.year, 12, 31) or start != date(start.year, 1, 1):
            raise CollectionError('Os períodos anuais precisam ser contíguos, sem sobreposição nem lacuna.')
    items, details = [], {}
    for snapshot, part_details in parts:
        for item in snapshot['items']:
            if item['id'] in details:
                raise CollectionError(f'{item["id"]}: decisão repetida em mais de um período.')
            details[item['id']] = part_details[item['id']]
            for segment in item.get('segments', []):
                details[segment['id']] = part_details[segment['id']]
            items.append(item)
    items.sort(key=lambda item: (item['date'], item['id']), reverse=True)
    counts = ('inventoryCount', 'candidateCount', 'reviewedCount', 'publishedCount', 'excludedCount',
              'pendingCount', 'missingTextCount', 'missingAbstentionCount', 'missingThemeCount', 'segmentCount')
    coverage = {key: sum(snapshot['coverage'].get(key, 0) for snapshot, _ in parts) for key in counts}
    period = {'start': parts[0][0]['period']['start'], 'end': parts[-1][0]['period']['end']}
    years = sorted({snapshot['period']['start'][:4] for snapshot, _ in parts})
    coverage['detail'] = _coverage_detail(coverage, years[0] if len(years) == 1 else f'{years[0]} a {years[-1]}')
    return {'schemaVersion': 1, 'generatedAt': utc_now(), 'period': period,
            'detailsVersion': hashlib.sha256(_json_bytes(details)).hexdigest(),
            'coverage': coverage, 'items': items}, details


def write_catalogue(snapshot, details, directory):
    # Each immutable generation becomes visible only through the final atomic index switch.
    version = snapshot['detailsVersion']
    if version != hashlib.sha256(_json_bytes(details)).hexdigest():
        raise CollectionError('A geração dos detalhes não corresponde ao índice.')
    directory.mkdir(parents=True, exist_ok=True)
    details_directory = directory / 'chamber-vote-details'
    details_directory.mkdir(parents=True, exist_ok=True)
    generation = details_directory / version
    if generation.exists():
        if any((generation / f'{identifier}.json').read_bytes() != _json_bytes(detail)
               for identifier, detail in details.items()):
            raise CollectionError('Geração existente de detalhes divergente; saída anterior preservada.')
    else:
        with tempfile.TemporaryDirectory(prefix='.staging-', dir=details_directory) as temporary:
            staged = Path(temporary) / version
            staged.mkdir()
            for identifier, detail in details.items():
                _atomic_bytes(staged / f'{identifier}.json', _json_bytes(detail))
            os.replace(staged, generation)
    _atomic_bytes(directory / 'chamber-votes.json', _json_bytes(snapshot))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--through', type=date.fromisoformat, action='append',
                        help='Fim de um inventário anual; repita para juntar anos contíguos.')
    parser.add_argument('--reviews', type=Path, help='Revisão alternativa; só com um único --through.')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args(argv)
    throughs = args.through or [date.today()]
    if args.reviews and len(throughs) > 1:
        parser.error('--reviews só pode ser usado com um único --through.')
    try:
        parts, entries, caches, segment_reviews = [], {}, {}, []
        for through in throughs:
            reviews_path = args.reviews or args.root / 'data' / 'reviews' / f'chamber-vote-reviews-{through}.json'
            inventory = json.loads((args.root / 'data' / 'reviews' / f'chamber-vote-inventory-{through}.json').read_text())
            reviews = json.loads(reviews_path.read_text())
            parts.append(build_catalogue(inventory, reviews, root=args.root, collect=args.collect, refresh=args.refresh))
            # Destaques e emendas revisados do período; ligados depois de juntar os anos, porque podem
            # pertencer a uma votação principal de um ano anterior.
            segments_path = args.root / 'data' / 'reviews' / f'chamber-vote-segment-reviews-{through}.json'
            if segments_path.exists():
                segment_reviews.extend(json.loads(segments_path.read_text()))
            cache = (args.root / 'data' / 'raw' / 'chamber-vote-inventory'
                     / f"{inventory['period']['start']}_{inventory['period']['end']}")
            for entry in inventory['entries']:
                entries[entry['id']] = entry
                caches[entry['id']] = cache
        snapshot, details = parts[0] if len(parts) == 1 else merge_catalogues(parts)
        if segment_reviews:
            details.update(build_segments(snapshot['items'], entries, segment_reviews, cache=caches.__getitem__,
                                          collect=args.collect, refresh=args.refresh, request=request_bytes))
            snapshot['coverage']['segmentCount'] = sum(len(item.get('segments', [])) for item in snapshot['items'])
            snapshot['detailsVersion'] = hashlib.sha256(_json_bytes(details)).hexdigest()
        write_catalogue(snapshot, details, args.root / 'data' / 'snapshots')
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Catálogo não gravado; saída anterior preservada: {error}\n')
    print(json.dumps(snapshot['coverage'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
