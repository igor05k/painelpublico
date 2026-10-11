/* Catálogo amplo de votações: carregado só ao entrar no Placar. */
const scoreboardState = {
  list: { status: 'idle', data: null, error: null, available: null, query: '', type: '', theme: '', result: '', page: 1, pageSize: 12 },
  listSequence: 0,
  detail: { id: null, status: 'idle', data: null, error: null, visibleParticipants: 20 },
  detailSequence: 0,
  detailCache: new Map(),
};
const SCOREBOARD_DETAIL_CACHE_LIMIT = 20;
const SCOREBOARD_VOTE_ID = /^\d+-\d+$/;
const SCOREBOARD_VOTE_LABELS = ['Sim', 'Não', 'Abstenção', 'Obstrução', 'Presidiu'];
// Cadeiras previstas em lei; não depende da lista de deputados do dia, que pode ter suplentes em troca.
const SCOREBOARD_CHAMBER_SEATS = 513;
const SCOREBOARD_TYPE_NAMES = { PL: 'Projeto de lei', PLP: 'Projeto de lei complementar', PEC: 'Proposta de emenda à Constituição' };
const SCOREBOARD_MONTHS = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
const SCOREBOARD_SEAT_GROUPS = [
  ['Sim', 'yes'], ['Não', 'no'], ['Abstenção', 'abstention'], ['Obstrução', 'obstruction'], ['Presidiu', 'chair'],
  ['Outro registro', 'other'], ['Escolha não informada', 'unknown'],
];
const scoreboardParticipantGroup = person => SCOREBOARD_VOTE_LABELS.includes(person?.vote) ? person.vote : person?.vote ? 'Outro registro' : 'Escolha não informada';

const scoreboardEscape = value => String(value == null ? '' : value).replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[character]));
const scoreboardText = value => typeof value === 'string' ? value.trim() : '';
const scoreboardCount = value => Number.isFinite(value) ? Number(value).toLocaleString('pt-BR') : '—';
function scoreboardDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(value)) return 'data não informada';
  return typeof formatShortDate === 'function' ? formatShortDate(value) : value.slice(0, 10).split('-').reverse().join('/');
}
function scoreboardPeriodDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(value)) return 'data não informada';
  return `${value.slice(8, 10)}/${value.slice(5, 7)}/${value.slice(0, 4)}`;
}
function scoreboardSafeSource(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    if (host !== 'camara.leg.br' && !host.endsWith('.camara.leg.br')) return null;
    return url.href;
  } catch (error) { return null; }
}
function scoreboardSourceLink(url, label) {
  const safeUrl = scoreboardSafeSource(url);
  return safeUrl ? `<a href="${scoreboardEscape(safeUrl)}" target="_blank" rel="noopener">${scoreboardEscape(label)} ↗</a>` : '';
}
function scoreboardOutcome(outcome, related) {
  if (related?.relation === 'approvedAfter' && outcome !== 'approved') return 'Versão rejeitada · projeto aprovado em seguida';
  return ({ approved: 'Aprovado nesta votação', rejected: 'Rejeitado nesta votação', not_approved: 'Não aprovado nesta votação' })[outcome] || 'Resultado não informado';
}
/* Decisões sobre trechos: o tipo diz como o trecho foi votado; o resultado, o que aconteceu com ele. */
const SCOREBOARD_SEGMENT_KINDS = { destaque: 'Votação em separado de um trecho', emenda: 'Emenda', emendas: 'Emendas votadas em bloco', emenda_redacao: 'Emenda de redação' };
const SCOREBOARD_SEGMENT_OUTCOMES = { kept: 'Trecho mantido', removed: 'Trecho retirado', approved: 'Aprovada', rejected: 'Rejeitada' };
function scoreboardSegments(segments) {
  const rows = Array.isArray(segments) ? segments.filter(segment => SCOREBOARD_VOTE_ID.test(scoreboardText(segment?.id))) : [];
  if (!rows.length) return '';
  return `<section class="card wide scoreboard-segments"><span class="k">Decisões sobre trechos do projeto</span>
    <p class="muted">Depois do texto principal, a Câmara votou separadamente ${rows.length === 1 ? 'esta parte' : `estas ${rows.length} partes`} do texto, com o voto de cada deputado. Um deputado pode apoiar o projeto e votar contra um trecho.</p>
    <ol class="scoreboard-segment-list">${rows.map(segment => {
      const tally = segment.tally || {};
      return `<li class="scoreboard-segment">
        <p class="scoreboard-segment-kind">${scoreboardEscape(SCOREBOARD_SEGMENT_KINDS[segment.kind] || 'Decisão sobre um trecho')} · ${scoreboardEscape(scoreboardDate(segment.date))}</p>
        <h3>${scoreboardEscape(segment.title || 'Título não informado')}</h3>
        ${segment.summary ? `<p>${scoreboardEscape(segment.summary)}</p>` : ''}
        <dl class="scoreboard-segment-meaning"><div><dt><i class="vote-yes"></i>Sim</dt><dd>${scoreboardEscape(segment.yesMeaning || 'Não informado')}</dd></div><div><dt><i class="vote-no"></i>Não</dt><dd>${scoreboardEscape(segment.noMeaning || 'Não informado')}</dd></div></dl>
        <div class="scoreboard-segment-result"><p class="scoreboard-outcome" data-outcome="${scoreboardEscape(segment.outcome || '')}">${scoreboardEscape(segment.decisionLabel || SCOREBOARD_SEGMENT_OUTCOMES[segment.outcome] || 'Resultado não informado')}</p>
          ${scoreboardTallyBar(tally)}<p class="scoreboard-meta"><span><b>${scoreboardCount(tally.yes)}</b> sim</span><span><b>${scoreboardCount(tally.no)}</b> não</span><span>${Number.isFinite(tally.abstention) ? `${scoreboardCount(tally.abstention)} abst.` : 'abst. não publicada'}</span></p></div>
        <button type="button" class="more" data-vote="${scoreboardEscape(segment.id)}">Ver como cada deputado votou →</button>
      </li>`;
    }).join('')}</ol></section>`;
}
function scoreboardParentDecision(parent) {
  if (!parent || !SCOREBOARD_VOTE_ID.test(scoreboardText(parent.id))) return '';
  return `<section class="card scoreboard-related" role="note"><span class="k">Parte de uma votação maior</span>
    <p>Esta é uma decisão sobre um trecho, ressalvado na votação do texto principal: <strong>${scoreboardEscape(parent.title || 'texto principal')}</strong> (${scoreboardEscape(scoreboardOutcome(parent.outcome).toLowerCase())}).</p>
    <button type="button" class="more" data-vote="${scoreboardEscape(parent.id)}">Ver a votação do texto principal →</button></section>`;
}
function scoreboardVoteType(item) {
  const type = scoreboardText(item?.type);
  if (['PL', 'PLP', 'PEC'].includes(type)) return type;
  const proposal = scoreboardText(item?.proposition);
  return (proposal.match(/^(PLP|PEC|PL)\b/i) || [])[1]?.toUpperCase() || '';
}
function scoreboardTypeBadge(type) {
  if (!type) return '';
  const name = SCOREBOARD_TYPE_NAMES[type] || type;
  return `<abbr class="scoreboard-type" data-type="${scoreboardEscape(type)}" title="${scoreboardEscape(name)}">${scoreboardEscape(type)}</abbr>`;
}
function scoreboardMonthKey(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}/.test(value) ? value.slice(0, 7) : '';
}
function scoreboardMonthLabel(key) {
  const month = SCOREBOARD_MONTHS[Number(key.slice(5, 7)) - 1];
  return month ? `${month[0].toUpperCase()}${month.slice(1)} de ${key.slice(0, 4)}` : 'Data não informada';
}
function scoreboardTallyBar(tally) {
  const parts = [['yes', tally?.yes], ['no', tally?.no], ['abstention', tally?.abstention]].filter(([, value]) => Number.isFinite(value) && value > 0);
  if (!parts.length) return '';
  const label = `Sim ${scoreboardCount(tally?.yes)}, Não ${scoreboardCount(tally?.no)}, ${Number.isFinite(tally?.abstention) ? `Abstenção ${scoreboardCount(tally.abstention)}` : 'abstenção não publicada'}`;
  return `<span class="scoreboard-bar" role="img" aria-label="${scoreboardEscape(label)}">${parts.map(([key, value]) => `<i class="vote-${key}" style="flex-grow:${Number(value)}"></i>`).join('')}</span>`;
}
function scoreboardListUrl() {
  const list = scoreboardState.list;
  const query = new URLSearchParams();
  if (list.query) query.set('q', list.query);
  if (list.type) query.set('type', list.type);
  if (list.theme) query.set('theme', list.theme);
  if (list.result) query.set('result', list.result);
  query.set('page', String(list.page));
  query.set('pageSize', String(list.pageSize));
  return `/api/c/votes?${query.toString()}`;
}
async function scoreboardGetJson(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || 'Não foi possível carregar as votações.');
    error.status = response.status;
    throw error;
  }
  return data;
}
function scoreboardRefresh() {
  if (typeof rerender === 'function') rerender();
}
function scoreboardLegacyVotes() {
  return Array.isArray(DATA?.votacoes) ? DATA.votacoes : [];
}
function scoreboardLegacyVisibleVotes() {
  const list = scoreboardState.list;
  const query = list.query.toLocaleLowerCase('pt-BR');
  return scoreboardLegacyVotes().filter(vote => {
    const type = scoreboardVoteType({ proposition: vote.proposicao });
    const haystack = [vote.proposicao, vote.titulo, vote.curto].filter(Boolean).join(' ').toLocaleLowerCase('pt-BR');
    const result = vote.aprovada === true ? 'approved' : vote.aprovada === false ? 'not_approved' : '';
    return (!query || haystack.includes(query)) && (!list.type || list.type === type) && !list.theme
      && (!list.result || list.result === result);
  });
}
function scoreboardCoverage(data) {
  const period = data?.period || {};
  const coverage = data?.coverage || {};
  const range = period.start || period.end ? `<p>Período consultado: ${scoreboardPeriodDate(period.start)} a ${scoreboardPeriodDate(period.end)}.</p>` : '';
  const year = /^\d{4}-/.test(period.start || '') && period.start?.slice(0, 4) === period.end?.slice(0, 4) ? period.start.slice(0, 4) : '';
  const timeframe = year ? `em ${year}` : 'no período consultado';
  const reviewed = scoreboardCount(coverage.reviewedCount);
  const published = scoreboardCount(coverage.publishedCount);
  const pending = scoreboardCount(coverage.pendingCount);
  const candidates = scoreboardCount(coverage.candidateCount);
  const excluded = Number.isInteger(coverage.excludedCount) && coverage.excludedCount >= 0
    ? `${scoreboardCount(coverage.excludedCount)} foram excluídos, cada um com o motivo e a fonte, e ` : '';
  const inventory = scoreboardCount(coverage.inventoryCount);
  const review = Number.isInteger(coverage.reviewedCount) && coverage.reviewedCount === coverage.candidateCount ? 'Revisamos todos' : `Revisamos ${reviewed}`;
  const pendingNote = coverage.pendingCount === 0 ? 'Nenhum ficou pendente.' : `${pending} ainda estão pendentes.`;
  const gapFields = ['missingTextCount', 'missingAbstentionCount', 'missingThemeCount'];
  const hasGapCounts = gapFields.every(field => Number.isInteger(coverage[field]) && coverage[field] >= 0);
  const gaps = [
    [coverage.missingTextCount, 'votação não tem link seguro para o texto exato votado.', 'votações não têm link seguro para o texto exato votado.'],
    [coverage.missingAbstentionCount, 'votação não tem a contagem de abstenções nas fontes que usamos.', 'votações não têm a contagem de abstenções nas fontes que usamos.'],
    [coverage.missingThemeCount, 'votação não tem tema oficial.', 'votações não têm tema oficial.'],
  ].filter(([count]) => Number.isInteger(count) && count >= 0)
    .map(([count, singular, plural]) => `<li>${scoreboardCount(count)} ${count === 1 ? singular : plural}</li>`).join('');
  const detail = scoreboardText(coverage.detail);
  const funnelSteps = [
    [coverage.inventoryCount, 'Registros de votação publicados pela Câmara', 'inventory'],
    [coverage.candidateCount, 'Pareciam votar o texto principal', 'candidates'],
    [coverage.publishedCount, 'Entraram no Placar', 'published'],
  ];
  const funnel = funnelSteps.every(([count]) => Number.isInteger(count) && count >= 0) && coverage.inventoryCount > 0
    ? `<ol class="scoreboard-funnel" aria-label="Como as votações foram selecionadas">${funnelSteps.map(([count, label, key]) => `<li><span>${label}</span><b>${scoreboardCount(count)}</b><i class="funnel-${key}" style="width:${Math.max(1.5, count / coverage.inventoryCount * 100).toFixed(2)}%"></i></li>`).join('')}</ol>` : '';
  const years = /^\d{4}-/.test(period.start || '') && /^\d{4}-/.test(period.end || '') ? `${period.start.slice(0, 4)}${period.start.slice(0, 4) === period.end.slice(0, 4) ? '' : `–${period.end.slice(2, 4)}`}` : '';
  const stats = `<dl class="scoreboard-stats">
      ${Number.isInteger(coverage.publishedCount) ? `<div><dt>Votações conferidas</dt><dd>${published}</dd></div>` : ''}
      <div><dt>Tipos de proposta</dt><dd>PL · PLP · PEC</dd></div>
      ${years ? `<div><dt>Período</dt><dd>${years}</dd></div>` : ''}
    </dl>`;
  return `${stats}<div class="card scoreboard-coverage"><h2 class="h">O que é o Placar</h2>
    <p>Aqui estão votações da Câmara ${timeframe} em que os deputados votaram o texto principal de um projeto de lei ou de uma mudança na Constituição, com o voto de cada um registrado.</p>
    <p><strong>${published} votações nominais conferidas</strong>, uma a uma, nas fontes oficiais. Elas não são tudo o que a Câmara votou ${year ? 'no ano' : 'no período'}. Um projeto aprovado aqui ainda pode não ter virado lei.</p>
    ${range}
    ${funnel}
    <details><summary>Como montamos este Placar e seus limites</summary>
      <p><strong>De onde vêm as votações.</strong> A Câmara publicou ${inventory} registros de votação ${timeframe}. Muitos são etapas do mesmo projeto: urgência, emendas, destaques, procedimentos e redação final. Ficamos só com as votações do texto principal de PL, PLP e PEC no Plenário. Votações simbólicas (sem registro de voto de cada deputado) e outros tipos de proposta ficam de fora.</p>
      <p><strong>Como escolhemos.</strong> Dos ${inventory} registros, ${candidates} pareciam votações do texto principal. ${review}: ${excluded}${published} entraram no Placar. ${pendingNote}</p>
      ${Number.isInteger(coverage.segmentCount) && coverage.segmentCount > 0 ? `<p><strong>Decisões sobre trechos.</strong> Em alguns projetos, mostramos também ${scoreboardCount(coverage.segmentCount)} ${coverage.segmentCount === 1 ? 'votação nominal' : 'votações nominais'} de destaques e emendas ressalvados no texto principal, com o que significava votar Sim e Não. É um piloto: cada uma é conferida no relatório nominal e no texto oficial do destaque ou da emenda, e elas não entram na contagem acima nem nas comparações entre deputados e partidos.</p>` : ''}
      <p><strong>Por que quase todas foram aprovadas.</strong> Antes da votação final, um projeto passa por comissões, pedidos de urgência e acordos entre os partidos. Quando não tem apoio, ele costuma parar no caminho: fica na comissão, é retirado da pauta ou é derrotado numa votação simbólica, sem registro do voto de cada deputado. As derrotas também aparecem em votações de emendas, destaques e requerimentos, que não entram aqui. Por isso, quando o texto principal chega a uma votação nominal, ele quase sempre é aprovado. Uma rejeição aqui pode ser de uma versão alternativa, como o substitutivo de uma comissão: nesse caso, a página da votação mostra a decisão seguinte, que aprovou o projeto.</p>
      <p><strong>Limites.</strong></p>
      <ul>${gaps}
        <li>O Placar ainda não cobre todo o mandato${year ? `, só ${year}` : ''}.</li>
        <li>O tema é o que a Câmara atribui ao projeto.</li>
        <li>Dado ausente não significa zero.</li>
        <li>O resultado mostrado é o daquela votação, não a situação atual do projeto.</li>
      </ul>
      ${!hasGapCounts && detail ? `<p>${scoreboardEscape(detail)}</p>` : ''}
    </details></div>`;
}
function scoreboardLegacyCard(vote) {
  const id = scoreboardText(vote.id);
  const type = scoreboardVoteType({ proposition: vote.proposicao });
  const tally = [vote.sim, vote.nao].map(scoreboardCount).join(' × ');
  const outcome = vote.aprovada === true ? 'Aprovado' : vote.aprovada === false ? 'Rejeitado' : 'Resultado não informado';
  return `<article class="card scoreboard-card">
    <span class="k">${scoreboardEscape(vote.proposicao || 'Proposição não informada')} · ${scoreboardEscape(scoreboardDate(vote.data))}</span>
    <h2 class="h">${scoreboardEscape(vote.titulo || 'Título não informado')}</h2>
    <p class="scoreboard-meta">${type ? `<span class="pill">${scoreboardEscape(type)}</span>` : ''}<span>${scoreboardEscape(tally)} · ${scoreboardEscape(outcome)}</span></p>
    ${vote.curto ? `<p class="muted">${scoreboardEscape(vote.curto)}</p>` : ''}
    ${SCOREBOARD_VOTE_ID.test(id) ? `<button type="button" class="more" data-vote="${scoreboardEscape(id)}">Entender essa votação</button>` : ''}
  </article>`;
}
function scoreboardItemCard(item) {
  const id = scoreboardText(item?.id);
  const themes = Array.isArray(item?.themes) ? item.themes.map(theme => scoreboardText(theme?.label)).filter(Boolean) : [];
  const tally = item?.tally || {};
  const type = scoreboardVoteType(item);
  const date = typeof item?.date === 'string' && /^\d{4}-\d{2}-\d{2}/.test(item.date) ? item.date : '';
  const abstention = Number.isFinite(tally.abstention) ? `${scoreboardCount(tally.abstention)} abst.` : 'abst. não publicada';
  return `<article class="card scoreboard-card">
    ${date ? `<p class="scoreboard-date" aria-hidden="true"><b>${date.slice(8, 10)}</b><span>${SCOREBOARD_MONTHS[Number(date.slice(5, 7)) - 1]?.slice(0, 3) || ''}</span></p>` : ''}
    <div class="scoreboard-card-body">
      <p class="scoreboard-kicker">${scoreboardTypeBadge(type)}<span class="k">${scoreboardEscape(item?.proposition || 'Proposição não informada')}<span${date ? ' class="sr-only"' : ''}> · ${scoreboardEscape(scoreboardDate(item?.date))}</span></span></p>
      <h3 class="h">${scoreboardEscape(item?.title || 'Título não informado')}</h3>
      ${item?.summary ? `<p class="muted scoreboard-summary">${scoreboardEscape(item.summary)}</p>` : ''}
      ${themes.length ? `<p class="scoreboard-themes">${themes.map(theme => `<span class="pill">${scoreboardEscape(theme)}</span>`).join(' ')}</p>` : ''}
      ${Number.isInteger(item?.segmentCount) && item.segmentCount > 0 ? `<p class="scoreboard-segment-count">+ ${item.segmentCount} ${item.segmentCount === 1 ? 'decisão sobre um trecho' : 'decisões sobre trechos'}, com voto de cada deputado</p>` : ''}
    </div>
    <div class="scoreboard-card-result">
      <p class="scoreboard-outcome" data-outcome="${scoreboardEscape(item?.outcome || '')}">${scoreboardEscape(scoreboardOutcome(item?.outcome, item?.related))}</p>
      ${scoreboardTallyBar(tally)}
      <p class="scoreboard-meta"><span><b>${scoreboardCount(tally.yes)}</b> sim</span><span><b>${scoreboardCount(tally.no)}</b> não</span><span>${abstention}</span></p>
      ${SCOREBOARD_VOTE_ID.test(id) ? `<button type="button" class="more" data-vote="${scoreboardEscape(id)}">Ver decisão e votos →</button>` : '<p class="muted">Identificador desta votação indisponível.</p>'}
    </div>
  </article>`;
}
function scoreboardGroupedCards(items) {
  const groups = [];
  for (const item of items) {
    const key = scoreboardMonthKey(item?.date);
    if (!groups.length || groups.at(-1).key !== key) groups.push({ key, items: [] });
    groups.at(-1).items.push(item);
  }
  return groups.map(group => `<section class="scoreboard-month"><h2>${scoreboardEscape(group.key ? scoreboardMonthLabel(group.key) : 'Data não informada')} <span>${group.items.length} ${group.items.length === 1 ? 'votação' : 'votações'} nesta página</span></h2>${group.items.map(scoreboardItemCard).join('')}</section>`).join('');
}
function scoreboardFilterForm(data, fallback) {
  const filters = data?.filters || {};
  const types = Array.isArray(filters.types) ? filters.types : ['PL', 'PLP', 'PEC'];
  const themes = Array.isArray(filters.themes) ? filters.themes : [];
  const list = scoreboardState.list;
  const resultOption = (value, label, title) => `<label class="scoreboard-chip"${title ? ` title="${scoreboardEscape(title)}"` : ''}><input type="radio" name="result" value="${scoreboardEscape(value)}"${list.result === value ? ' checked' : ''}><span>${scoreboardEscape(label)}</span></label>`;
  const typeOption = (value, label, title) => `<label class="scoreboard-chip"${title ? ` title="${scoreboardEscape(title)}"` : ''}><input type="radio" name="type" value="${scoreboardEscape(value)}"${list.type === value ? ' checked' : ''}><span>${scoreboardEscape(label)}</span></label>`;
  return `<form class="card wide scoreboard-filters" data-scoreboard-filter-form aria-label="Filtros do Placar">
    <div class="scoreboard-search-row">
      <label class="scoreboard-search"><span class="sr-only">Buscar votação</span><input name="q" type="search" value="${scoreboardEscape(list.query)}" maxlength="120" placeholder="Busque por projeto, título ou assunto"></label>
      <button class="scoreboard-submit" type="submit">Buscar</button>
    </div>
    <div class="scoreboard-filter-row">
      <fieldset class="scoreboard-chips"><legend class="sr-only">Tipo de proposta</legend>${typeOption('', 'Todos os tipos', '')}${types.map(type => typeOption(type, type, SCOREBOARD_TYPE_NAMES[type] || '')).join('')}</fieldset>
      <fieldset class="scoreboard-chips"><legend class="sr-only">Resultado da votação</legend>${resultOption('', 'Todos os resultados', '')}${resultOption('approved', 'Aprovadas', 'Texto aprovado nesta votação')}${resultOption('not_approved', 'Rejeitadas', 'Texto rejeitado ou não aprovado nesta votação; pode ser uma versão alternativa, e o projeto ter sido aprovado em seguida')}</fieldset>
      ${fallback ? `<p class="muted">Temas oficiais ficam disponíveis quando o catálogo ampliado está ativo.</p>` : `<label class="scoreboard-theme"><span class="sr-only">Tema oficial</span><select name="theme" data-scoreboard-autosubmit><option value="">Todos os temas</option>${themes.map(theme => `<option value="${scoreboardEscape(theme.id)}"${list.theme === theme.id ? ' selected' : ''}>${scoreboardEscape(theme.label)}</option>`).join('')}</select></label>`}
      <p class="scoreboard-legend" aria-hidden="true"><span><i class="vote-yes"></i>Sim</span><span><i class="vote-no"></i>Não</span><span><i class="vote-abstention"></i>Abstenção</span></p>
    </div>
  </form>`;
}
function scoreboardPagination(data, fallbackCount) {
  const page = Number.isInteger(data?.page) ? data.page : scoreboardState.list.page;
  const pageCount = Number.isInteger(data?.pageCount) ? data.pageCount : Math.max(1, Math.ceil(fallbackCount / scoreboardState.list.pageSize));
  const total = Number.isFinite(data?.total) ? data.total : fallbackCount;
  if (pageCount <= 1) return `<p class="muted scoreboard-result-count">${scoreboardCount(total)} votações neste resultado.</p>`;
  return `<nav class="scoreboard-pagination" aria-label="Paginação das votações">
    <button type="button" class="fchip" data-scoreboard-page="${Math.max(1, page - 1)}"${page <= 1 ? ' disabled' : ''} aria-label="Página anterior">‹ Anterior</button>
    <span aria-live="polite">Página ${page} de ${pageCount} · ${scoreboardCount(total)} votações</span>
    <button type="button" class="fchip" data-scoreboard-page="${Math.min(pageCount, page + 1)}"${page >= pageCount ? ' disabled' : ''} aria-label="Próxima página">Próxima ›</button>
  </nav>`;
}
function scoreboardVotesView() {
  const list = scoreboardState.list;
  const fallback = list.available === false || (list.status === 'error' && (!list.data || list.data.available === false));
  const data = list.data && list.data.available !== false ? list.data : null;
  const legacyVotes = fallback ? scoreboardLegacyVisibleVotes() : [];
  const legacyStart = (list.page - 1) * list.pageSize;
  const visibleLegacy = legacyVotes.slice(legacyStart, legacyStart + list.pageSize);
  const items = Array.isArray(data?.items) ? data.items : [];
  const unavailableNote = fallback ? '<p class="scoreboard-fallback" role="status">O catálogo ampliado está indisponível. Esta tela mostra apenas as votações selecionadas que já existem neste painel.</p>' : '';
  const loading = list.status === 'loading' ? '<p class="scoreboard-status" role="status" aria-live="polite">Carregando votações…</p>' : '';
  const error = list.status === 'error' ? `<div class="scoreboard-error" role="alert"><p>${scoreboardEscape(list.error || 'Não foi possível carregar o catálogo ampliado.')}</p><button type="button" class="fchip" data-scoreboard-retry>Tentar novamente</button></div>` : '';
  const result = fallback ? visibleLegacy.map(scoreboardLegacyCard).join('') : scoreboardGroupedCards(items);
  const empty = list.status === 'ready' && !fallback && items.length === 0 || fallback && legacyVotes.length === 0
    ? '<p class="card scoreboard-empty">Nenhuma votação encontrada com esses filtros.</p>' : '';
  const paginationData = fallback ? null : data;
  return `${pageHead('Câmara · Plenário', 'Placar', fallback ? 'Consulte as votações selecionadas e suas fontes oficiais.' : 'Veja o que foi decidido sobre o texto principal dos projetos e como cada deputado votou.')}
    ${data ? scoreboardCoverage(data) : ''}
    ${unavailableNote}
    ${scoreboardFilterForm(data, fallback)}
    ${loading}${error}
    <div class="scoreboard-results" aria-live="polite">${result || empty}</div>
    ${result ? scoreboardPagination(paginationData, fallback ? legacyVotes.length : Number(data?.total) || 0) : ''}
    <span class="src">Fonte: Câmara dos Deputados · dados abertos do Plenário.</span>`;
}
function scoreboardRelatedDecision(related) {
  if (!related || !SCOREBOARD_VOTE_ID.test(scoreboardText(related.id))) return '';
  const tally = `Sim ${scoreboardCount(related.tally?.yes)} × Não ${scoreboardCount(related.tally?.no)}`;
  const link = `<button type="button" class="more" data-vote="${scoreboardEscape(related.id)}">`;
  if (related.relation === 'approvedAfter') {
    return `<section class="card scoreboard-related" role="note"><span class="k">O que valeu para o projeto</span>
      <p>Esta votação decidiu sobre uma <strong>versão alternativa</strong> do texto, que foi rejeitada. Na mesma sessão, logo depois, a Câmara aprovou o projeto (${scoreboardEscape(tally)}).</p>
      ${link}Ver a votação que aprovou o projeto →</button></section>`;
  }
  if (related.relation === 'rejectedBefore') {
    return `<section class="card scoreboard-related" role="note"><span class="k">Antes desta votação</span>
      <p>Na mesma sessão, a Câmara rejeitou antes uma versão alternativa do texto (${scoreboardEscape(tally)}). Esta é a votação que aprovou o projeto.</p>
      ${link}Ver a versão rejeitada →</button></section>`;
  }
  return '';
}
function scoreboardDetailSources(sources, dataNotes) {
  const source = sources || {};
  const links = [
    [source.vote, 'Registro da votação', 'Dados Abertos da Câmara'],
    [source.rollCall, 'Relatório nominal', 'Voto de cada deputado'],
    [source.text, 'Texto votado', 'Versão do texto decidida'],
    [source.decision, 'Decisão na Câmara', 'Registro da decisão em Plenário'],
    [source.proposition, 'Ficha da proposição', 'Tramitação da proposta'],
    [source.referenceProposition, 'Proposição de referência nos Dados Abertos', ''],
  ].map(([url, label, note]) => {
    const link = scoreboardSourceLink(url, label);
    return link ? `<li>${link}${note ? `<small>${note}</small>` : ''}</li>` : '';
  }).filter(Boolean);
  const notes = Array.isArray(dataNotes) ? dataNotes.filter(note => typeof note === 'string').map(note => `<p class="muted">${scoreboardEscape(note)}</p>`).join('') : '';
  const missingText = source.text === null ? '<p class="muted">O link seguro para o texto exato votado ainda não está disponível. O relatório e o registro da decisão permanecem nas fontes.</p>' : '';
  return `<section class="card scoreboard-sources"><span class="k">Fontes oficiais</span>${links.length ? `<ul class="scoreboard-source-links">${links.join('')}</ul>` : '<p class="muted">Links oficiais não informados para esta votação.</p>'}${missingText}${notes}</section>`;
}
function scoreboardSeatGrid(participants) {
  const rows = Array.isArray(participants) ? participants : [];
  if (!rows.length) return '';
  if (rows.length > SCOREBOARD_CHAMBER_SEATS) {
    return `<p class="scoreboard-seat-warning" role="note">A lista nominal tem ${scoreboardCount(rows.length)} registros, mais que as ${SCOREBOARD_CHAMBER_SEATS} cadeiras da Câmara (por exemplo, numa troca de suplente no dia). Por isso o quadro de cadeiras não é exibido; os votos individuais estão abaixo.</p>`;
  }
  const counts = new Map(SCOREBOARD_SEAT_GROUPS.map(([label]) => [label, 0]));
  rows.forEach(person => { const group = scoreboardParticipantGroup(person); counts.set(group, (counts.get(group) || 0) + 1); });
  const empty = SCOREBOARD_CHAMBER_SEATS - rows.length;
  const present = SCOREBOARD_SEAT_GROUPS.filter(([label]) => counts.get(label) > 0);
  const seats = present.map(([label, key]) => `<i class="seat-${key}"></i>`.repeat(counts.get(label))).join('') + '<i class="seat-empty"></i>'.repeat(empty);
  const legend = present.map(([label, key]) => `<span><i class="seat-${key}"></i>${scoreboardEscape(label)} ${scoreboardCount(counts.get(label))}</span>`).join('')
    + (empty ? `<span><i class="seat-empty"></i>Sem voto registrado ${scoreboardCount(empty)}</span>` : '');
  const label = present.map(([group]) => `${group} ${counts.get(group)}`).concat(empty ? [`sem voto registrado ${empty}`] : []).join(', ');
  return `<div class="scoreboard-seats" role="img" aria-label="${scoreboardEscape(`Cadeiras da Câmara: ${label}`)}">${seats}</div>
    <p class="scoreboard-seat-legend">${legend}</p>
    <p class="muted scoreboard-seat-note">Cada ponto é uma das ${SCOREBOARD_CHAMBER_SEATS} cadeiras previstas em lei. ${empty ? '“Sem voto registrado” junta ausências, licenças e quem não votou; a fonte não diz o motivo. ' : ''}Dado ausente não significa zero.</p>`;
}
function scoreboardParticipants(participants) {
  const search = typeof document !== 'undefined' ? document.querySelector('[data-scoreboard-participant-search]')?.value || '' : '';
  const query = search.trim().toLocaleLowerCase('pt-BR');
  const rows = Array.isArray(participants) ? participants : [];
  const matches = rows.filter(person => `${person?.name || ''} ${person?.party || ''} ${person?.uf || ''} ${person?.vote || ''}`.toLocaleLowerCase('pt-BR').includes(query));
  const visible = matches.slice(0, scoreboardState.detail.visibleParticipants);
  const sections = SCOREBOARD_VOTE_LABELS.concat(['Outro registro', 'Escolha não informada']).map(label => {
    const group = visible.filter(person => scoreboardParticipantGroup(person) === label);
    if (!group.length) return '';
    return `<section class="scoreboard-voter-group"><h3>${scoreboardEscape(label)} <span>${scoreboardCount(matches.filter(person => scoreboardParticipantGroup(person) === label).length)}</span></h3><ul>${group.map(person => {
      const name = scoreboardText(person?.name) || 'Nome não informado';
      const id = scoreboardText(person?.id);
      const politician = id.match(/^camara:(\d+)$/);
      const href = politician ? `/deputado/${politician[1]}` : '';
      const meta = [SCOREBOARD_VOTE_LABELS.includes(person?.vote) ? '' : scoreboardText(person?.vote), scoreboardText(person?.party), scoreboardText(person?.uf)].filter(Boolean).join(' · ');
      return `<li>${href ? `<a href="${href}" data-deputy="camara:${politician[1]}">${scoreboardEscape(name)}</a>` : `<span>${scoreboardEscape(name)}</span>`}${meta ? `<small>${scoreboardEscape(meta)}</small>` : ''}</li>`;
    }).join('')}</ul></section>`;
  }).join('');
  const more = matches.length > visible.length ? `<button type="button" class="fchip" data-scoreboard-more>Mostrar mais ${Math.min(20, matches.length - visible.length)} (${scoreboardCount(matches.length - visible.length)} restantes)</button>` : '';
  const empty = matches.length === 0 ? '<p class="muted">Nenhum registro individual corresponde à busca.</p>' : '';
  return `<section class="card scoreboard-voters"><span class="k">Como votou cada deputado</span>
    <label>Buscar parlamentar<input class="search" type="search" data-scoreboard-participant-search value="${scoreboardEscape(search)}" maxlength="100" placeholder="Seu deputado: nome, partido, UF ou voto" aria-label="Buscar nos votos individuais"></label>
    ${rows.length ? `<p class="muted">${scoreboardCount(matches.length)} registros${query ? ' encontrados' : ' nesta votação'}.</p>` : '<p class="muted">Nenhum registro individual foi fornecido para esta consulta.</p>'}
    ${sections}${empty}${more}</section>`;
}
function scoreboardPartyTotals(partyTotals) {
  const rows = Array.isArray(partyTotals) ? partyTotals : [];
  if (!rows.length) return '';
  const value = number => Number.isFinite(number) && number > 0 ? Number(number) : 0;
  const total = row => value(row?.yes) + value(row?.no) + value(row?.other);
  const max = Math.max(1, ...rows.map(total));
  const sorted = [...rows].sort((a, b) => total(b) - total(a) || String(a?.party || '').localeCompare(String(b?.party || ''), 'pt-BR'));
  return `<section class="card scoreboard-parties"><span class="k">Resumo por partido</span><p class="muted">Partido no registro desta votação, do maior para o menor.</p><ul class="scoreboard-party-totals">${sorted.map(row => {
    const name = scoreboardEscape(row?.party || 'Partido não informado');
    const counts = `Sim ${scoreboardCount(row?.yes)} · Não ${scoreboardCount(row?.no)} · Outros ${scoreboardCount(row?.other)}`;
    const bars = [['yes', row?.yes], ['no', row?.no], ['other', row?.other]].filter(([, n]) => value(n) > 0)
      .map(([key, n]) => `<i class="vote-${key}" style="width:${(value(n) / max * 100).toFixed(2)}%"></i>`).join('');
    return `<li><b>${name}</b><span class="scoreboard-party-bar" role="img" aria-label="${name}: ${counts}">${bars}</span><span>${counts}</span></li>`;
  }).join('')}</ul></section>`;
}
function scoreboardDetailView() {
  const detail = scoreboardState.detail;
  if (detail.id !== String(state.voteId || '')) return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button><p class="scoreboard-status" role="status" aria-live="polite">Carregando detalhes e votos individuais…</p>`;
  if (detail.status === 'legacy') return typeof selectedVoteView === 'function' ? selectedVoteView() : '<p class="note">Esta votação está disponível no recorte selecionado.</p>';
  if (detail.status === 'loading' || detail.status === 'idle') return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button><p class="scoreboard-status" role="status" aria-live="polite">Carregando detalhes e votos individuais…</p>`;
  if (detail.status === 'missing') return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button><section class="card scoreboard-error" role="alert"><h1 class="h">Votação não encontrada</h1><p>O identificador não está disponível no catálogo público.</p></section>`;
  if (detail.status === 'error') return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button><section class="card scoreboard-error" role="alert"><p>${scoreboardEscape(detail.error || 'Não foi possível carregar esta votação.')}</p><button type="button" class="fchip" data-scoreboard-retry>Carregar novamente</button></section>`;
  const payload = detail.data || {};
  const vote = payload.vote || {};
  const tally = vote.tally || {};
  const themes = Array.isArray(vote.themes) ? vote.themes.map(theme => scoreboardText(theme?.label)).filter(Boolean) : [];
  const isSegment = Boolean(vote.parent);
  const outcome = isSegment ? (vote.decisionLabel || SCOREBOARD_SEGMENT_OUTCOMES[vote.outcome] || 'Resultado não informado') : scoreboardOutcome(vote.outcome, vote.related);
  const hasParticipants = payload.participantsAvailable !== false;
  const type = scoreboardVoteType(vote);
  const participants = Array.isArray(payload.participants) ? payload.participants : [];
  const pecNote = type === 'PEC' && !isSegment ? `<p class="muted scoreboard-pec-note">PEC precisa de 308 votos favoráveis (3/5 da Câmara) em cada um dos dois turnos.</p>` : '';
  return `<button type="button" class="back" data-back>‹ Voltar ao Placar</button>
    <header class="scoreboard-detail-head">
      <p class="scoreboard-kicker">${scoreboardTypeBadge(type)}${type ? `<span class="scoreboard-type-name">${scoreboardEscape(isSegment ? SCOREBOARD_SEGMENT_KINDS[vote.kind] || 'Decisão sobre um trecho' : SCOREBOARD_TYPE_NAMES[type])}</span>` : ''}<span class="k">${scoreboardEscape(vote.proposition || 'Proposição não informada')} · votado em ${scoreboardEscape(scoreboardDate(vote.date))}</span></p>
      <h1 class="h scoreboard-detail-title">${scoreboardEscape(vote.title || 'Título não informado')}</h1>
      <p class="scoreboard-themes"><span class="scoreboard-outcome" data-outcome="${scoreboardEscape(vote.outcome || '')}">${scoreboardEscape(outcome)}</span>${themes.map(theme => `<span class="pill">${scoreboardEscape(theme)}</span>`).join(' ')}</p>
    </header>
    <section class="card scoreboard-decision"><span class="k">O que foi decidido</span><h2 class="h">${scoreboardEscape(vote.decisionLabel || 'Decisão não informada')}</h2>${vote.summary ? `<p>${scoreboardEscape(vote.summary)}</p>` : '<p class="muted">Resumo não informado para esta versão.</p>'}
      <div class="scoreboard-meaning"><div><span class="k"><i class="vote-yes"></i>Sim significava</span><p>${scoreboardEscape(vote.yesMeaning || 'Informação não disponível neste registro.')}</p></div><div><span class="k"><i class="vote-no"></i>Não significava</span><p>${scoreboardEscape(vote.noMeaning || 'Informação não disponível neste registro.')}</p></div></div>
      ${pecNote}<p class="muted">O resultado é o desta votação, não a situação atual da proposta.</p></section>
    ${scoreboardRelatedDecision(vote.related)}
    ${scoreboardParentDecision(vote.parent)}
    <section class="card scoreboard-result"><span class="k">Resultado desta votação</span><dl class="scoreboard-tally"><div><dt>Sim</dt><dd>${scoreboardCount(tally.yes)}</dd></div><div><dt>Não</dt><dd>${scoreboardCount(tally.no)}</dd></div><div><dt>Abstenção</dt><dd>${scoreboardCount(tally.abstention)}</dd>${Number.isFinite(tally.abstention) ? '' : '<small>não publicada</small>'}</div><div><dt>Total</dt><dd>${scoreboardCount(tally.total)}</dd></div></dl>
      ${hasParticipants ? scoreboardSeatGrid(participants) : ''}
      <p class="muted">${scoreboardEscape(outcome)}. O resultado se refere a esta decisão registrada. O total soma Sim, Não e Abstenção.</p></section>
    ${hasParticipants ? scoreboardParticipants(payload.participants) : '<section class="card scoreboard-voters"><span class="k">Votos individuais</span><p class="muted">A lista individual não está disponível para esta votação.</p></section>'}
    ${scoreboardPartyTotals(payload.partyTotals)}
    ${scoreboardSegments(vote.segments)}
    ${scoreboardDetailSources(vote.sources, vote.dataNotes)}
    <span class="src">Fonte: Câmara dos Deputados · revisão em ${scoreboardEscape(scoreboardPeriodDate(vote.reviewedAt))}. O resultado descreve esta votação, sem indicar a situação atual da proposta.</span>`;
}
function scoreboardLoadList() {
  const list = scoreboardState.list;
  const sequence = ++scoreboardState.listSequence;
  list.status = 'loading';
  list.error = null;
  const url = scoreboardListUrl();
  scoreboardRefresh();
  return scoreboardGetJson(url).then(data => {
    if (sequence !== scoreboardState.listSequence) return;
    if (!data || data.available === false) {
      list.available = false;
      list.data = data || null;
      list.status = 'ready';
    } else {
      list.available = true;
      list.data = data;
      list.status = 'ready';
    }
    scoreboardRefresh();
  }).catch(error => {
    if (sequence !== scoreboardState.listSequence) return;
    if (error.status === 404) {
      list.available = false;
      list.data = { available: false };
      list.status = 'ready';
      list.error = null;
    } else {
      list.status = 'error';
      list.error = error.message || 'Não foi possível carregar o catálogo ampliado.';
    }
    scoreboardRefresh();
  });
}
function scoreboardCacheDetail(id, payload) {
  const cache = scoreboardState.detailCache;
  if (cache.has(id)) cache.delete(id);
  cache.set(id, payload);
  while (cache.size > SCOREBOARD_DETAIL_CACHE_LIMIT) cache.delete(cache.keys().next().value);
}
function scoreboardLoadDetail(id) {
  if (!SCOREBOARD_VOTE_ID.test(String(id || ''))) {
    scoreboardState.detail = { id, status: 'missing', data: null, error: null, visibleParticipants: 20 };
    return Promise.resolve();
  }
  const cached = scoreboardState.detailCache.get(id);
  const sequence = ++scoreboardState.detailSequence;
  if (cached) {
    scoreboardState.detail = { id, status: 'ready', data: cached, error: null, visibleParticipants: 20 };
    scoreboardRefresh();
    return Promise.resolve();
  }
  scoreboardState.detail = { id, status: 'loading', data: null, error: null, visibleParticipants: 20 };
  scoreboardRefresh();
  return scoreboardGetJson(`/api/c/votes/${encodeURIComponent(id)}`).then(data => {
    if (sequence !== scoreboardState.detailSequence || state.view !== 'vote' || String(state.voteId) !== id) return;
    if (!data || data.available === false) {
      if (VOTES_BY_ID[id]) scoreboardState.detail = { id, status: 'legacy', data: null, error: null, visibleParticipants: 20 };
      else scoreboardState.detail = { id, status: 'missing', data: null, error: null, visibleParticipants: 20 };
    } else {
      scoreboardCacheDetail(id, data);
      scoreboardState.detail = { id, status: 'ready', data, error: null, visibleParticipants: 20 };
    }
    scoreboardRefresh();
  }).catch(error => {
    if (sequence !== scoreboardState.detailSequence || state.view !== 'vote' || String(state.voteId) !== id) return;
    if (VOTES_BY_ID[id]) scoreboardState.detail = { id, status: 'legacy', data: null, error: null, visibleParticipants: 20 };
    else if (error.status === 404) scoreboardState.detail = { id, status: 'missing', data: null, error: null, visibleParticipants: 20 };
    else scoreboardState.detail = { id, status: 'error', data: null, error: error.message || 'Não foi possível carregar esta votação.', visibleParticipants: 20 };
    scoreboardRefresh();
  });
}
function scoreboardViewEntered(view) {
  if (view !== 'vote' && scoreboardState.detail.status === 'loading') {
    scoreboardState.detailSequence++;
    scoreboardState.detail.status = 'idle';
  }
  if (view === 'votes' && scoreboardState.list.status === 'idle') scoreboardLoadList();
  if (view === 'vote' && scoreboardState.detail.id !== String(state.voteId)) scoreboardLoadDetail(String(state.voteId || ''));
  if (view === 'vote' && scoreboardState.detail.id === String(state.voteId) && scoreboardState.detail.status === 'idle') scoreboardLoadDetail(String(state.voteId || ''));
}
function scoreboardApplyFilters(values) {
  const list = scoreboardState.list;
  list.query = scoreboardText(values?.query).slice(0, 120);
  list.type = ['PL', 'PLP', 'PEC'].includes(values?.type) ? values.type : '';
  list.theme = scoreboardText(values?.theme).slice(0, 80);
  list.result = ['approved', 'not_approved'].includes(values?.result) ? values.result : '';
  list.page = 1;
  return scoreboardLoadList();
}
function scoreboardHandlePage(page) {
  const data = scoreboardState.list.data;
  const pageCount = Number.isInteger(data?.pageCount) ? data.pageCount : Math.max(1, Math.ceil(scoreboardLegacyVisibleVotes().length / scoreboardState.list.pageSize));
  const target = Number(page);
  if (!Number.isInteger(target) || target < 1 || target > pageCount || target === scoreboardState.list.page) return;
  scoreboardState.list.page = target;
  return scoreboardLoadList();
}
function scoreboardHandleClick(event, target) {
  if (target?.hasAttribute('data-scoreboard-page')) { scoreboardHandlePage(target.dataset.scoreboardPage); return true; }
  if (target?.hasAttribute('data-scoreboard-retry')) {
    if (state.view === 'vote') scoreboardLoadDetail(String(state.voteId || ''));
    else scoreboardLoadList();
    return true;
  }
  if (target?.hasAttribute('data-scoreboard-more')) {
    scoreboardState.detail.visibleParticipants += 20;
    scoreboardRefresh();
    return true;
  }
  return false;
}
if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('submit', event => {
    const form = event.target?.closest?.('[data-scoreboard-filter-form]');
    if (!form) return;
    event.preventDefault();
    const formData = new FormData(form);
    scoreboardApplyFilters({ query: formData.get('q'), type: formData.get('type'), theme: formData.get('theme'), result: formData.get('result') });
  });
  document.addEventListener('change', event => {
    const field = event.target;
    if (!field?.matches?.('[data-scoreboard-filter-form] input[name="type"], [data-scoreboard-filter-form] input[name="result"], [data-scoreboard-autosubmit]')) return;
    const form = field.closest('[data-scoreboard-filter-form]');
    if (form?.requestSubmit) form.requestSubmit();
  });
  document.addEventListener('input', event => {
    if (!event.target?.matches?.('[data-scoreboard-participant-search]')) return;
    scoreboardState.detail.visibleParticipants = 20;
    const caret = event.target.selectionStart;
    scoreboardRefresh();
    const replacement = document.querySelector('[data-scoreboard-participant-search]');
    if (replacement?.focus) {
      replacement.focus();
      if (caret != null && replacement.setSelectionRange) replacement.setSelectionRange(caret, caret);
    }
  });
}
