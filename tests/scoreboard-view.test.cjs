const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadApp({ pathname = '/', fetch: fetchImpl = () => Promise.resolve(jsonResponse({ available: true, items: [], total: 0, page: 1, pageSize: 12, pageCount: 0 })) } = {}) {
  const app = { innerHTML: '' };
  const listeners = {};
  const document = {
    body: { dataset: {} },
    getElementById: id => id === 'app' ? app : null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener(name, handler) { (listeners[name] ||= []).push(handler); },
  };
  const votes = JSON.parse(fs.readFileSync(path.join(__dirname, '../frontend/data/votes.json'), 'utf8'));
  const data = { votacoes: votes.map(vote => ({ ...vote, partidos: [] })), presencaTodos: [], votosCompletos: {},
    arrecadacao: null, perfis: { profiles: {} }, senado: {}, ultimaVotacao: null };
  const names = ['dates.js', 'profile-data.js', 'profile-cost.js', 'profile-senate-cost.js', 'share-card.js', 'citizen-view.js',
    'extras-view.js', 'parties-view.js', 'home-view.js', 'city-view.js', 'scoreboard-view.js', 'app.script.js'];
  const source = names.map(name => fs.readFileSync(path.join(__dirname, '../frontend/scripts', name), 'utf8')).join('\n');
  const context = vm.createContext({
    document, window: { scrollY: 0, scrollTo() {}, addEventListener() {} }, location: { protocol: 'http:', pathname }, URL, URLSearchParams, FormData,
    history: { pushState() {}, replaceState() {} }, fetch: fetchImpl,
    setTimeout: () => 1, clearTimeout() {}, matchMedia: () => ({ matches: false, addEventListener() {} }),
    MutationObserver: class { observe() {} }, addEventListener() {}, requestAnimationFrame() {},
  });
  vm.runInContext(source.replace('/*DATA*/null', JSON.stringify(data)), context);
  const click = dataset => {
    const target = { dataset, hasAttribute: name => Object.hasOwn(dataset, name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())) };
    for (const handler of listeners.click || []) {
      handler({ target: { closest: selector => selector.split(',').some(item => target.hasAttribute(item.slice(1, -1))) ? target : null }, preventDefault() {} });
    }
  };
  return { context, app, document, votes, click };
}
function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function listPayload({ items = [], page = 1, pageCount = 1, total = items.length } = {}) {
  return { available: true, items, total, page, pageSize: 12, pageCount,
    period: { start: '2023-02-01', end: '2026-10-09' },
    coverage: { inventoryCount: 1339, candidateCount: 162, reviewedCount: 40, publishedCount: 7, pendingCount: 155, detail: 'metodologia' },
    filters: { types: ['PL', 'PLP', 'PEC'], themes: [{ id: 'tributos', label: 'Tributos' }] }, generatedAt: '2026-10-09T12:00:00Z' };
}
function item(id, title, extra = {}) {
  return { id, date: '2026-10-08', proposition: 'PL 123/2026', type: 'PL', title, summary: 'Resumo da decisão', decisionLabel: 'Substitutivo aprovado',
    yesMeaning: 'Aprovar a versão descrita.', noMeaning: 'Rejeitar a versão descrita.', outcome: 'approved', tally: { yes: 250, no: 100, abstention: null, total: 350 },
    themes: [{ id: 'tributos', label: 'Tributos' }], sources: {}, ...extra };
}

test('the home makes no Placar request; entering the view loads the catalogue', async () => {
  const calls = [];
  const { context, app } = loadApp({ fetch: async url => { calls.push(url); return jsonResponse(listPayload()); } });
  assert.deepEqual(calls, []);
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  assert.equal(calls.length, 1);
  assert.match(calls[0], /^\/api\/c\/votes\?/);
  assert.match(app.innerHTML, /O que é o Placar/);
});

test('filter parameters, coverage counts and page navigation follow the API result', async () => {
  const calls = [];
  const { context, app } = loadApp({ fetch: async url => {
    calls.push(url);
    const page = Number(new URL(url, 'https://local.test').searchParams.get('page'));
    return jsonResponse(listPayload({ items: [item(`2611313-${page}`, `Votação da página ${page}`)], page, pageCount: 3, total: 25 }));
  } });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  await vm.runInContext("scoreboardApplyFilters({query:'benefício', type:'PL', theme:'tributos'})", context);
  assert.match(calls.at(-1), /q=benef%C3%ADcio/);
  assert.match(calls.at(-1), /type=PL/);
  assert.match(calls.at(-1), /theme=tributos/);
  assert.match(app.innerHTML, /7 votações/);
  assert.match(app.innerHTML, /Revisamos 40/);
  assert.match(app.innerHTML, /155 ainda estão pendentes/);
  assert.match(app.innerHTML, /Página 1 de 3 · 25 votações/);
  await vm.runInContext('scoreboardHandlePage(2)', context);
  assert.match(calls.at(-1), /page=2/);
  assert.match(app.innerHTML, /Votação da página 2/);
  assert.match(app.innerHTML, /Página 2 de 3 · 25 votações/);
});

test('coverage distinguishes exclusions from pending decisions without inventing missing counts', async () => {
  const { context } = loadApp();
  const legacy = vm.runInContext(`scoreboardCoverage(${JSON.stringify(listPayload())})`, context);
  assert.doesNotMatch(legacy, /foram excluídos/);
  const data = listPayload();
  data.coverage = { ...data.coverage, reviewedCount: 162, excludedCount: 150, pendingCount: 5 };
  const current = vm.runInContext(`scoreboardCoverage(${JSON.stringify(data)})`, context);
  assert.match(current, /7 votações/);
  assert.match(current, /Revisamos todos: 150 foram excluídos, cada um com o motivo e a fonte, e 7 entraram no Placar/);
  assert.match(current, /5 ainda estão pendentes/);
});

test('official source notes preserve report fallback provenance and escape external text', () => {
  const { context } = loadApp();
  const html = vm.runInContext(`scoreboardDetailSources({}, ${JSON.stringify([
    'Votos conferidos no relatório nominal; Dados Abertos sem linhas.', '<script>alert(1)</script>'
  ])})`, context);
  assert.match(html, /Votos conferidos no relatório nominal; Dados Abertos sem linhas/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test('stale catalogue responses cannot replace the newest filter result', async () => {
  const pending = [];
  const { context, app } = loadApp({ fetch: url => new Promise(resolve => pending.push({ url, resolve })) });
  vm.runInContext("navigateToView('votes')", context);
  const newest = vm.runInContext("scoreboardApplyFilters({query:'novo', type:'PEC', theme:''})", context);
  pending[1].resolve(jsonResponse(listPayload({ items: [item('2611313-32', 'Resultado novo')] })));
  await newest;
  assert.match(app.innerHTML, /Resultado novo/);
  pending[0].resolve(jsonResponse(listPayload({ items: [item('2611313-31', 'Resultado antigo')] })));
  await flush();
  assert.match(app.innerHTML, /Resultado novo/);
  assert.doesNotMatch(app.innerHTML, /Resultado antigo/);
});

test('a stale vote detail cannot replace the currently open decision', async () => {
  const pending = [];
  const { context, app, click } = loadApp({ fetch: url => {
    if (url.startsWith('/api/c/votes?')) return Promise.resolve(jsonResponse(listPayload({ items: [item('2611313-31', 'Primeira'), item('2611313-32', 'Segunda')] })));
    return new Promise(resolve => pending.push({ url, resolve }));
  } });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  click({ vote: '2611313-31' });
  click({ vote: '2611313-32' });
  assert.deepEqual(pending.map(request => request.url), ['/api/c/votes/2611313-31', '/api/c/votes/2611313-32']);
  pending[1].resolve(jsonResponse({ available: true, vote: item('2611313-32', 'Decisão atual'), participants: [], partyTotals: [], participantsAvailable: true }));
  await flush();
  assert.match(app.innerHTML, /Decisão atual/);
  pending[0].resolve(jsonResponse({ available: true, vote: item('2611313-31', 'Decisão antiga'), participants: [], partyTotals: [], participantsAvailable: true }));
  await flush();
  assert.match(app.innerHTML, /Decisão atual/);
  assert.doesNotMatch(app.innerHTML, /Decisão antiga/);
});

test('detail loads lazily, preserves missing values and escapes text and source links', async () => {
  const calls = [];
  const participants = Array.from({ length: 21 }, (_, index) => ({ id: `camara:${1000 + index}`, name: `Deputado ${index}`, party: 'ABC', uf: 'SP',
    vote: ['Sim', 'Não', 'Abstenção', 'Obstrução', 'Presidiu'][index % 5] }));
  participants[19].vote = null;
  const detail = { available: true, vote: item('2611313-31', '<img src=x onerror=alert(1)>', {
    summary: '<script>ruim</script>', tally: { yes: 12, no: 3, abstention: null },
    sources: { vote: 'javascript:alert(1)', rollCall: 'https://fora.example/nominal', text: 'https://www.camara.leg.br/texto?id=4', proposition: 'https://camara.leg.br/prop/123', referenceProposition: 'https://www.camara.leg.br/prop/42' },
  }), participants, partyTotals: [], participantsAvailable: true };
  const { context, app, click } = loadApp({ fetch: async url => {
    calls.push(url);
    return url.startsWith('/api/c/votes?') ? jsonResponse(listPayload({ items: [item('2611313-31', 'Decisão')] })) : jsonResponse(detail);
  } });
  assert.deepEqual(calls, []);
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  assert.deepEqual(calls, ['/api/c/votes?page=1&pageSize=12']);
  click({ vote: '2611313-31' });
  await flush();
  assert.ok(calls.includes('/api/c/votes/2611313-31'));
  assert.match(app.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(app.innerHTML, /&lt;script&gt;ruim&lt;\/script&gt;/);
  assert.doesNotMatch(app.innerHTML, /href="javascript:|href="https:\/\/fora\.example/);
  assert.match(app.innerHTML, /href="https:\/\/www\.camara\.leg\.br\/texto\?id=4/);
  assert.match(app.innerHTML, /href="https:\/\/www\.camara\.leg\.br\/prop\/42"[^>]*>Proposição de referência nos Dados Abertos/);
  assert.match(app.innerHTML, /Abstenção<\/dt><dd>—/);
  assert.match(app.innerHTML, /Total<\/dt><dd>—/);
  assert.match(app.innerHTML, /Escolha não informada/);
  assert.match(app.innerHTML, /Mostrar mais 1/);
  assert.doesNotMatch(app.innerHTML, /Não votou/);
  vm.runInContext("scoreboardHandleClick({}, {hasAttribute: name => name === 'data-scoreboard-more', dataset: {}})", context);
  assert.match(app.innerHTML, /Deputado 20/);
  assert.match(app.innerHTML, /href="\/deputado\/1020"/);
});

test('an unavailable catalogue shows only selected legacy cards and legacy detail still opens', async () => {
  const calls = [];
  const { context, app, votes, click } = loadApp({ fetch: async url => {
    calls.push(url);
    return jsonResponse({ error: 'rota indisponível' }, 404);
  } });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  assert.match(app.innerHTML, /O catálogo ampliado está indisponível/);
  assert.match(app.innerHTML, /votações selecionadas que já existem neste painel/);
  assert.ok(votes.some(vote => app.innerHTML.includes(vote.titulo)));
  click({ vote: String(votes[0].id) });
  await flush();
  assert.match(app.innerHTML, /O que muda na prática/);
  assert.ok(calls.includes(`/api/c/votes/${votes[0].id}`));
});

test('the seat grid uses the 513 seats in law, keeps the chair apart and never shows negative empty seats', () => {
  const { context } = loadApp();
  const people = votes => votes.map((vote, index) => ({ id: `camara:${index}`, name: `Deputado ${index}`, party: 'ABC', uf: 'SP', vote }));
  const html = vm.runInContext(`scoreboardSeatGrid(${JSON.stringify(people([...Array(472).fill('Sim'), ...Array(22).fill('Não'), 'Obstrução', 'Presidiu']))})`, context);
  assert.equal((html.match(/<i class="seat-/g) || []).length, 513 + 5);
  assert.match(html, /Presidiu 1/);
  assert.match(html, /seat-chair/);
  assert.match(html, /Sim 472/);
  assert.match(html, /Sem voto registrado 17/);
  const crowded = vm.runInContext(`scoreboardSeatGrid(${JSON.stringify(people(Array(514).fill('Sim')))})`, context);
  assert.match(crowded, /514 registros, mais que as 513 cadeiras/);
  assert.doesNotMatch(crowded, /class="scoreboard-seats"/);
  assert.equal(vm.runInContext('scoreboardSeatGrid([])', context), '');
});

test('the detail hides the seat grid without a roll call and shows the PEC quorum only for PEC', async () => {
  const pec = item('2233802-424', 'Jornada de trabalho', { proposition: 'PEC 221/2019', type: 'PEC' });
  const responses = {
    '/api/c/votes/2233802-424': { available: true, vote: pec, participants: [], partyTotals: [], participantsAvailable: false },
    '/api/c/votes/2611313-31': { available: true, vote: item('2611313-31', 'Projeto comum'), participants: [{ id: 'camara:1', name: 'A', party: 'ABC', uf: 'SP', vote: 'Sim' }], partyTotals: [], participantsAvailable: true },
  };
  const { context, app, click } = loadApp({ fetch: async url => jsonResponse(url.startsWith('/api/c/votes?') ? listPayload({ items: [pec] }) : responses[url]) });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  click({ vote: '2233802-424' });
  await flush();
  assert.match(app.innerHTML, /308 votos favoráveis \(3\/5 da Câmara\) em cada um dos dois turnos/);
  assert.doesNotMatch(app.innerHTML, /class="scoreboard-seats"/);
  assert.match(app.innerHTML, /A lista individual não está disponível/);
  click({ vote: '2611313-31' });
  await flush();
  assert.doesNotMatch(app.innerHTML, /308 votos/);
  assert.match(app.innerHTML, /class="scoreboard-seats"/);
});

test('opening a deputy from a vote keeps the vote as the back destination', () => {
  const { context, click } = loadApp();
  vm.runInContext("Object.assign(state, { view: 'vote', voteId: '2233802-424' })", context);
  click({ deputy: 'camara:1020' });
  assert.equal(vm.runInContext('state.view', context), 'profile');
  assert.equal(vm.runInContext('state.politicianId', context), 'camara:1020');
  click({ back: '' });
  assert.equal(vm.runInContext('state.view', context), 'vote');
  assert.equal(vm.runInContext('state.voteId', context), '2233802-424');
});

test('the result filter is sent to the API and the coverage explains why rejections are rare', async () => {
  const calls = [];
  const { context, app } = loadApp({ fetch: async url => { calls.push(url); return jsonResponse(listPayload({ items: [item('1-1', 'Decisão')] })); } });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  assert.match(app.innerHTML, /name="result" value="not_approved"/);
  assert.match(app.innerHTML, /Por que quase todas foram aprovadas/);
  vm.runInContext("scoreboardApplyFilters({ query: '', type: '', theme: '', result: 'not_approved' })", context);
  await flush();
  assert.ok(calls.at(-1).includes('result=not_approved'));
  vm.runInContext("scoreboardApplyFilters({ result: 'invalido' })", context);
  await flush();
  assert.ok(!calls.at(-1).includes('result='));
});

test('a rejected alternative version links to the approval that followed', async () => {
  const related = { id: '1-2', relation: 'approvedAfter', outcome: 'approved', tally: { yes: 407, no: 6, abstention: null, total: 413 } };
  const detail = { available: true, vote: item('1-1', 'Versão rejeitada', { outcome: 'rejected', related }), participants: [], partyTotals: [], participantsAvailable: false };
  const { context, app, click } = loadApp({ fetch: async url => url.startsWith('/api/c/votes?')
    ? jsonResponse(listPayload({ items: [item('1-1', 'Versão rejeitada', { outcome: 'rejected', related })] })) : jsonResponse(detail) });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  assert.match(app.innerHTML, /Versão rejeitada · projeto aprovado em seguida/);
  click({ vote: '1-1' });
  await flush();
  assert.match(app.innerHTML, /O que valeu para o projeto/);
  assert.match(app.innerHTML, /data-vote="1-2"/);
  assert.match(app.innerHTML, /Sim 407 × Não 6/);
});

test('decisions on parts of the text list under the main vote and open as their own page', async () => {
  const segment = { id: '1-5', date: '2026-10-08', kind: 'destaque', title: 'Destaque <do> art. 1º', summary: 'Destaque para retirar o art. 1º.',
    decisionLabel: 'Artigo mantido', yesMeaning: 'Manter o art. 1º.', noMeaning: 'Retirar o art. 1º.', outcome: 'kept',
    tally: { yes: 284, no: 86, abstention: 3, total: 373 }, sources: {} };
  const main = { available: true, vote: item('1-1', 'Texto principal', { segments: [segment] }), participants: [], partyTotals: [], participantsAvailable: false };
  const part = { available: true, vote: { ...segment, proposition: 'PL 123/2026', type: 'PL', themes: [], parent: { id: '1-1', title: 'Texto principal', outcome: 'approved' } },
    participants: [], partyTotals: [], participantsAvailable: false };
  const { context, app, click } = loadApp({ fetch: async url => url.startsWith('/api/c/votes?')
    ? jsonResponse(listPayload({ items: [item('1-1', 'Texto principal', { segmentCount: 1 })] }))
    : jsonResponse(url.endsWith('/1-5') ? part : main) });
  vm.runInContext("navigateToView('votes')", context);
  await flush();
  assert.match(app.innerHTML, /\+ 1 decisão sobre um trecho, com voto de cada deputado/);
  click({ vote: '1-1' });
  await flush();
  assert.match(app.innerHTML, /Decisões sobre trechos do projeto/);
  assert.match(app.innerHTML, /Além do texto principal/);
  assert.match(app.innerHTML, /Votação em separado de um trecho/);
  assert.match(app.innerHTML, /Destaque &lt;do&gt; art\. 1º/);
  assert.match(app.innerHTML, /Manter o art\. 1º\./);
  assert.match(app.innerHTML, /Artigo mantido/);
  assert.match(app.innerHTML, /data-vote="1-5"/);
  click({ vote: '1-5' });
  await flush();
  assert.match(app.innerHTML, /Parte de uma votação maior/);
  assert.match(app.innerHTML, /data-vote="1-1"/);
  assert.doesNotMatch(app.innerHTML, /PEC precisa de 308/);
  assert.doesNotMatch(app.innerHTML, /Decisões sobre trechos do projeto/);
});
