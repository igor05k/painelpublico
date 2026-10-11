"""Decisões sobre trechos (destaques e emendas) ligadas a uma votação já publicada no Placar.

Cada decisão vem de uma revisão editorial local e só é publicada depois de conferida contra o
registro da API, o relatório nominal oficial e os votos individuais. Falha fechado, como o catálogo.
"""
from __future__ import annotations

import re

from ingest.chamber_vote_inventory import API_BASE, CollectionError, _load, _paged
from ingest.chamber_vote_report import identify_participants, parse_roll_call
from ingest.chamber_vote_rules import _recorded_partial_tally

SEGMENT_KINDS = {'destaque', 'emenda', 'emendas', 'emenda_redacao', 'dispositivos'}
# "kept"/"removed": votação em separado de um trecho; "approved"/"rejected": emendas.
SEGMENT_OUTCOMES = {'approved', 'rejected', 'kept', 'removed'}
SEGMENT_FIELDS = ('title', 'summary', 'decisionLabel', 'yesMeaning', 'noMeaning')


def build_segments(items, inventory_entries, reviews, *, cache, collect, refresh, request):
    """Valida as revisões e pendura cada decisão na votação principal; devolve os detalhes novos."""
    # Importado aqui: chamber_votes chama esta função e guarda as regras comuns de conferência.
    from ingest.chamber_votes import (PROPOSITION_LABEL as proposition_label, VOTE_ID as vote_id,
                                      _nominal_report as nominal_report, _official_source as official_source,
                                      _registered_after_report as registered_after_report, _source_bytes,
                                      _valid_review_date as valid_date, normalize_participants)
    if not isinstance(reviews, list):
        raise CollectionError('A revisão de trechos deve ser uma lista.')
    # Um cache por inventário anual: com vários anos, cada decisão usa o cache do seu ano.
    cache_for = cache if callable(cache) else (lambda _identifier: cache)
    parents = {item['id']: item for item in items}
    details, seen = {}, set()
    for review in reviews:
        identifier = review.get('id') if isinstance(review, dict) else None
        if not isinstance(identifier, str) or not vote_id.fullmatch(identifier) or identifier in seen or identifier in parents:
            raise CollectionError('Revisão de trecho sem ID válido, repetida ou igual a uma votação principal.')
        seen.add(identifier)
        if review.get('status') != 'confirmed':
            if review.get('status') not in ('pending', 'excluded') or not review.get('reason'):
                raise CollectionError(f'{identifier}: trecho não confirmado precisa de motivo.')
            continue
        parent = parents.get(review.get('parentId'))
        if parent is None or identifier.split('-')[0] != parent['id'].split('-')[0]:
            raise CollectionError(f'{identifier}: trecho sem votação principal publicada da mesma proposição.')
        entry = inventory_entries.get(identifier)
        prefix = parent['id'].split('-')[0]
        # Destaques podem ser votados em outra sessão (até meses depois do texto-base), mas pertencem
        # à última votação principal publicada da proposição, sem outra votação principal no meio.
        later_main = [item['id'] for item in items if item['id'].split('-')[0] == prefix
                      and parent['date'] < item['date'] <= (entry or {}).get('date', '')]
        if entry is None or entry['date'] < parent['date'] or later_main:
            raise CollectionError(f'{identifier}: trecho fora do inventário ou de outra votação principal.')
        # No mesmo dia (dois turnos de PEC, por exemplo), a ordem dos relatórios nominais decide.
        order = _roll_call_number((review.get('sources') or {}).get('rollCall') if isinstance(review.get('sources'), dict) else None)
        same_day = [number for item in items if item['id'].split('-')[0] == prefix and item['date'] == entry['date']
                    and (number := _roll_call_number(item['sources'].get('rollCall'))) is not None]
        parent_order = _roll_call_number(parent['sources'].get('rollCall'))
        notes_before = []
        if order is not None and parent_order is not None:
            if parent_order < order:
                misplaced = any(parent_order < other < order for other in same_day)
            else:
                # Votada antes do texto principal na mesma sessão (emenda saneadora, por exemplo): vale só
                # para a primeira votação principal da sessão, sem outra antes do trecho.
                misplaced = parent['date'] != entry['date'] or any(other < parent_order and other != parent_order
                                                                   for other in same_day)
                notes_before = ['Votada na mesma sessão, antes da votação do texto principal.']
            if misplaced:
                raise CollectionError(f'{identifier}: outra votação principal da sessão fica entre o texto ligado e o trecho.')
        evidence, sources = review.get('evidence'), review.get('sources')
        if (review.get('kind') not in SEGMENT_KINDS or review.get('outcome') not in SEGMENT_OUTCOMES
                or not valid_date(review.get('reviewedAt'))
                or any(not isinstance(review.get(field), str) or not review[field].strip() for field in SEGMENT_FIELDS)
                or not isinstance(review.get('reportObject'), str) or not review['reportObject'].strip()
                or not isinstance(evidence, dict) or any(not evidence.get(field) for field in ('method', 'object', 'text'))
                or not isinstance(sources, dict)):
            raise CollectionError(f'{identifier}: revisão de trecho incompleta.')
        notes = review.get('dataNotes', [])
        if not isinstance(notes, list) or len(notes) > 4 or any(not isinstance(note, str) or not note.strip() for note in notes):
            raise CollectionError(f'{identifier}: notas de dados inválidas.')
        notes = [*notes, *notes_before]
        segment_cache = cache_for(identifier)
        safe_sources = {key: official_source(sources.get(key)) for key in ('rollCall', 'text', 'proposition')}

        url = f'{API_BASE}/votacoes/{identifier}'
        payload, detail_source = _load(url, segment_cache / 'details' / f'{identifier}.json',
                                       collect=collect, refresh=refresh, request=request, detail=True)
        record = payload['dados']
        if record.get('id') != identifier or record.get('data') != entry['date']:
            raise CollectionError(f'{identifier}: registro da API não confirma a decisão.')
        if review['outcome'] != api_outcome(record.get('descricao'), record.get('aprovacao')):
            raise CollectionError(f'{identifier}: resultado da revisão diverge do registro da API.')

        content, report_source = _source_bytes(safe_sources['rollCall'], segment_cache / 'reports' / f'{identifier}.html',
                                               collect=collect, refresh=refresh, request=request)
        if not nominal_report(content):
            raise CollectionError(f'{identifier}: relatório não confirma método nominal eletrônico.')
        report = parse_roll_call(content)
        match = proposition_label.fullmatch(parent['proposition'])
        allowed = [{'type': match.group(1), 'number': int(match.group(2)), 'year': int(match.group(3))}] if match else []
        # Projeto apensado: o relatório pode usar a numeração da proposição dos Dados Abertos (a afetada
        # pelo próprio registro, com o mesmo ID), enquanto a votação principal publicada usa a votada.
        for affected in record.get('proposicoesAfetadas') or []:
            if isinstance(affected, dict) and str(affected.get('id')) == prefix:
                allowed.append({'type': affected.get('siglaTipo'), 'number': affected.get('numero'), 'year': affected.get('ano')})
        if allowed and report['proposition'] != allowed[0] and report['proposition'] in allowed:
            label = f"{report['proposition']['type']} {report['proposition']['number']}/{report['proposition']['year']}"
            notes = [*notes, f'O relatório nominal identifica a proposição pela numeração dos Dados Abertos ({label}); '
                             f"a votação principal publicada usa {parent['proposition']}."]
        if (report['date'] != entry['date'] or report['proposition'] not in allowed
                or report['object'] != review['reportObject']
                or not registered_after_report(report['endedAt'], record.get('dataHoraRegistro'))):
            raise CollectionError(f'{identifier}: relatório não corresponde à proposição, objeto e horário da decisão.')
        api_tally = _recorded_partial_tally(record.get('descricao'))
        if api_tally.get('yes') is None:
            raise CollectionError(f'{identifier}: a API não publica placar nominal.')
        chair = sum(row.get('vote') in ('Artigo 17', 'Presidiu') for row in report['participants'])
        if (chair and api_tally.get('total') is not None and report['tally'].get('total') is not None
                and api_tally['total'] == report['tally']['total'] + chair):
            # O total do relatório soma Sim, Não e Abstenção; o da API às vezes inclui quem presidiu.
            api_tally = {**api_tally, 'total': None}
            notes = [*notes, 'O total da descrição da API inclui o registro de quem presidiu a sessão (art. 17); '
                             'o Placar usa o total do relatório nominal, com Sim, Não e Abstenção.']
        for key, value in api_tally.items():
            if value is not None and report['tally'].get(key) is not None and value != report['tally'][key]:
                raise CollectionError(f'{identifier}: placar da API diverge do relatório nominal.')
        tally = {key: value if value is not None else report['tally'].get(key) for key, value in api_tally.items()}
        if api_tally.get('no') is None:
            if tally['no'] is None:
                raise CollectionError(f'{identifier}: placar nominal sem votos Não em nenhuma fonte.')
            notes = [*notes, 'A descrição da API não traz os votos Não; a contagem vem do relatório nominal oficial.']

        rows, participant_sources = _paged(f'{url}/votos', segment_cache / 'participants' / identifier,
                                           collect=collect, refresh=refresh, request=request)
        origin, identity_sources = 'api', []
        if not rows:
            deputies, identity_sources = _paged(
                f'{API_BASE}/deputados?dataInicio={entry["date"]}&dataFim={entry["date"]}&itens=100',
                segment_cache / 'deputies' / entry['date'], collect=collect, refresh=refresh, request=request)
            rows, origin = identify_participants(report['participants'], deputies), 'rollCall'
            notes = [*notes, 'Os votos individuais vêm do relatório nominal oficial. A lista dos Dados Abertos está vazia nesta decisão.']
        participants, party_totals = normalize_participants(rows, tally)

        segment = {'id': identifier, 'date': entry['date'], 'kind': review['kind'],
                   **{field: review[field] for field in SEGMENT_FIELDS}, 'outcome': review['outcome'], 'tally': tally,
                   'sources': {'vote': url, **safe_sources}, 'reviewedAt': review['reviewedAt'],
                   'registeredAt': str(record.get('dataHoraRegistro') or ''),
                   **({'dataNotes': notes} if notes else {})}
        parent.setdefault('segments', []).append(segment)
        details[identifier] = {'id': identifier, 'participants': participants, 'partyTotals': party_totals,
                               'sourceMetadata': {'vote': detail_source, 'rollCall': report_source,
                                                  'participants': participant_sources,
                                                  **({'participantsOrigin': origin, 'identities': identity_sources}
                                                     if origin == 'rollCall' else {})}}
    for item in items:
        if 'segments' in item:
            # Na ordem em que a Câmara registrou as votações na sessão.
            item['segments'].sort(key=lambda segment: (segment.pop('registeredAt'), segment['id']))
    return details



def _roll_call_number(url):
    """Número sequencial do relatório nominal (ideVotacao), quando o link o traz."""
    match = re.search(r'[?&]ideVotacao=(\d+)', url or '')
    return int(match.group(1)) if match else None


# A descrição da API diz o resultado de forma explícita ("Mantido o texto", "Suprimido o texto",
# "Rejeitada a Emenda...", "Aprovadas as Emendas..."); o campo aprovacao, quando existe, tem de concordar.
_DESCRIBED_OUTCOMES = (('mantid', 'kept'), ('suprimid', 'removed'), ('rejeitad', 'rejected'), ('aprovad', 'approved'))
_APPROVAL_OUTCOMES = {1: {'approved'}, 0: {'rejected'}, None: {'kept', 'removed'}}


def api_outcome(description, approval):
    """Resultado que a API afirma para a decisão, ou None quando as fontes da API não bastam ou se contradizem."""
    first = str(description or '').strip().split(' ', 1)[0].casefold()
    described = next((outcome for prefix, outcome in _DESCRIBED_OUTCOMES if first.startswith(prefix)), None)
    allowed = _APPROVAL_OUTCOMES.get(approval)
    if described is None or allowed is None or described not in allowed:
        return None
    return described
