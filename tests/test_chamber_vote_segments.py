import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from ingest import chamber_votes
from ingest.chamber_vote_inventory import CollectionError
from test_chamber_votes import THROUGH, VOTE_ID, FakeChamberAPI, encoded, inventory, participant, review

SEGMENT_ID = "123-5"
SEGMENT_ROLL_CALL = "https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?ideVotacao=99"
OBJECT = "DTQ 1 - ABC - EMENDA DE PLENÁRIO Nº 1"


def segment_report(*, obj=OBJECT, yes=1, no=2, day="09/10/2026"):
    rows = "".join(f"<tr><td>Deputado {index}</td><td>SP</td><td>{choice}</td></tr>"
                   for index, choice in enumerate(["Sim"] * yes + ["Não"] * no, 1))
    return (f"<p>SESSÃO EXTRAORDINÁRIA Nº 1 - {day}</p>"
            f"<p>Abertura da sessão: {day} 11:00<br>Encerramento da sessão: {day} 13:00</p>"
            f"<p>Proposição: PL Nº 1/2026 - {obj} - Nominal Eletrônica</p>"
            f"<p>Início da votação: {day} 12:20<br>Encerramento da votação: {day} 12:30</p>"
            f'<div id="listaVotacao"><table><tr><th>Sim:</th><td>{yes}</td></tr>'
            f'<tr><th>Não:</th><td>{no}</td></tr><tr><th>Total da Votação:</th><td>{yes + no}</td></tr></table></div>'
            '<div id="listagem"><table><thead><tr><th>Parlamentar</th><th>UF</th><th>Voto</th></tr></thead>'
            f'<tbody><tr><th colspan="3">ABC</th></tr>{rows}'
            f'<tr><td colspan="3">Total ABC: {yes + no}</td></tr></tbody></table></div>').encode("utf-8")


def segment_review(**changes):
    return {
        "id": SEGMENT_ID, "parentId": VOTE_ID, "status": "confirmed", "reviewedAt": "2026-10-10",
        "kind": "emenda", "title": "Emenda da bancada ABC", "summary": "Destaque para votar a emenda nº 1.",
        "decisionLabel": "Emenda rejeitada", "yesMeaning": "Incluir a emenda.", "noMeaning": "Deixar a emenda de fora.",
        "outcome": "rejected", "reportObject": OBJECT,
        "sources": {"rollCall": SEGMENT_ROLL_CALL,
                    "text": "https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=1",
                    "proposition": "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=7"},
        "evidence": {"method": "relatório nominal", "object": "destaque 1", "text": "inteiro teor da emenda"},
        **changes,
    }


class SegmentAPI(FakeChamberAPI):
    """Adds the separate vote on part of the text to the offline API fixture."""

    def __init__(self, *, aprovacao=0, report=None, registered="12:30:40", description=None):
        super().__init__()
        self.segment = {"id": SEGMENT_ID, "data": THROUGH, "aprovacao": aprovacao,
                        "dataHoraRegistro": f"{THROUGH}T{registered}",
                        "descricao": description or "Rejeitada a Emenda de Plenário nº 1. Sim: 1; Não: 2; Total: 3."}
        self.segment_report = report or segment_report()

    def __call__(self, url):
        path = urlsplit(url).path
        if url == SEGMENT_ROLL_CALL:
            self.calls.append(url)
            return self.segment_report
        if path == f"/api/v2/votacoes/{SEGMENT_ID}":
            self.calls.append(url)
            return encoded({"dados": self.segment, "links": []})
        if path == f"/api/v2/votacoes/{SEGMENT_ID}/votos":
            self.calls.append(url)
            return encoded({"dados": [participant(1, "Sim"), participant(2, "Não"), participant(3, "Não")], "links": []})
        return super().__call__(url)


def segment_inventory():
    data = inventory()
    data["voteCount"] = 2
    data["entries"].append({"id": SEGMENT_ID, "date": THROUGH, "candidate": False})
    return data


class ChamberVoteSegmentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, segments, api=None):
        # Pasta nova a cada chamada: o cache de uma fonte já baixada é reaproveitado de propósito.
        root = Path(tempfile.mkdtemp(dir=self.root))
        return chamber_votes.build_catalogue(segment_inventory(), [review()], root=root, collect=True,
                                             request=api or SegmentAPI(), segment_reviews=segments)

    def test_confirmed_segment_hangs_on_the_main_vote_with_its_own_roll_call(self):
        snapshot, details = self.build([segment_review()])
        segment = snapshot["items"][0]["segments"][0]
        self.assertEqual(segment["id"], SEGMENT_ID)
        self.assertEqual(segment["tally"], {"yes": 1, "no": 2, "abstention": None, "total": 3})
        self.assertEqual(segment["outcome"], "rejected")
        self.assertEqual(segment["sources"]["vote"].rsplit("/", 1)[1], SEGMENT_ID)
        self.assertNotIn("registeredAt", segment)
        self.assertEqual([person["vote"] for person in details[SEGMENT_ID]["participants"]], ["Sim", "Não", "Não"])
        self.assertEqual(snapshot["coverage"]["segmentCount"], 1)
        # A decisão principal continua contada sozinha: o trecho não entra nos candidatos nem nos publicados.
        self.assertEqual(snapshot["coverage"]["publishedCount"], 1)

    def test_without_segment_reviews_the_catalogue_is_unchanged(self):
        snapshot, details = self.build(None)
        self.assertNotIn("segments", snapshot["items"][0])
        self.assertEqual(snapshot["coverage"]["segmentCount"], 0)
        self.assertEqual(set(details), {VOTE_ID})

    def test_outcome_must_match_the_api_approval_field(self):
        with self.assertRaisesRegex(CollectionError, "resultado da revisão diverge"):
            self.build([segment_review(outcome="kept")])
        with self.assertRaisesRegex(CollectionError, "resultado da revisão diverge"):
            self.build([segment_review(outcome="approved")])

    def test_explicit_api_description_decides_kept_or_removed(self):
        removed = "Suprimido o texto. Sim: 1; Não: 2; Total: 3."
        with self.assertRaisesRegex(CollectionError, "resultado da revisão diverge"):
            self.build([segment_review(outcome="kept")], api=SegmentAPI(aprovacao=None, description=removed))
        snapshot, _ = self.build([segment_review(outcome="removed")], api=SegmentAPI(aprovacao=None, description=removed))
        self.assertEqual(snapshot["items"][0]["segments"][0]["outcome"], "removed")
        # Sem verbo de resultado na descrição, nem "aprovacao" basta para escolher entre manter e retirar.
        with self.assertRaisesRegex(CollectionError, "resultado da revisão diverge"):
            self.build([segment_review(outcome="kept")],
                       api=SegmentAPI(aprovacao=None, description="Resultado. Sim: 1; Não: 2; Total: 3."))

    def test_api_outcome_requires_description_and_approval_to_agree(self):
        from ingest.chamber_vote_segments import api_outcome
        self.assertEqual(api_outcome("Mantido o texto. Sim: 1", None), "kept")
        self.assertEqual(api_outcome("Rejeitadas as Emendas de Plenário.", 0), "rejected")
        self.assertEqual(api_outcome("Aprovada a Emenda de Redação nº 4.", 1), "approved")
        self.assertIsNone(api_outcome("Aprovada a Emenda nº 1.", 0))
        self.assertIsNone(api_outcome("Suprimido o texto.", 1))
        self.assertIsNone(api_outcome("Resultado. Sim: 1", None))

    def test_report_object_tally_and_timing_must_match(self):
        with self.assertRaisesRegex(CollectionError, "relatório não corresponde"):
            self.build([segment_review(reportObject="DTQ 2 - ABC - EMENDA DE PLENÁRIO Nº 2")])
        with self.assertRaisesRegex(CollectionError, "placar da API diverge"):
            self.build([segment_review()], api=SegmentAPI(report=segment_report(yes=2, no=1)))
        with self.assertRaisesRegex(CollectionError, "relatório não corresponde"):
            self.build([segment_review()], api=SegmentAPI(registered="14:00:00"))

    def test_missing_no_count_in_the_api_comes_from_the_report_with_a_note(self):
        api = SegmentAPI(description="Rejeitada a Emenda de Plenário nº 1. Sim: 1; Total: 3.")
        snapshot, _ = self.build([segment_review()], api=api)
        segment = snapshot["items"][0]["segments"][0]
        self.assertEqual(segment["tally"]["no"], 2)
        self.assertIn("relatório nominal", segment["dataNotes"][-1])

    def test_segment_needs_a_published_parent_of_the_same_proposition(self):
        with self.assertRaisesRegex(CollectionError, "sem votação principal"):
            self.build([segment_review(parentId="999-1")])
        with self.assertRaisesRegex(CollectionError, "ID válido"):
            self.build([segment_review(id=VOTE_ID)])

    def test_segment_cannot_predate_its_main_vote(self):
        data = segment_inventory()
        data["entries"][1]["date"] = "2026-10-08"
        api = SegmentAPI()
        api.segment["data"] = "2026-10-08"
        with self.assertRaisesRegex(CollectionError, "outra votação principal"):
            chamber_votes.build_catalogue(data, [review()], root=Path(tempfile.mkdtemp(dir=self.root)), collect=True,
                                          request=api, segment_reviews=[segment_review()])

    def test_same_day_order_follows_roll_call_numbers(self):
        # A votação principal do fixture não tem ideVotacao; com um relatório anterior ao do trecho, passa.
        parent_review = {**review(), "sources": {**review()["sources"], "rollCall": SEGMENT_ROLL_CALL.replace("=99", "=98")}}
        from ingest.chamber_vote_segments import _roll_call_number
        self.assertEqual(_roll_call_number(SEGMENT_ROLL_CALL), 99)
        self.assertIsNone(_roll_call_number("https://www.camara.leg.br/votacoes/123-1/relatorio"))
        self.assertEqual(_roll_call_number(parent_review["sources"]["rollCall"]), 98)

    def direct(self, parent, api, review_changes=None, cache=None):
        """Chama build_segments direto, com a votação principal montada no teste."""
        from ingest.chamber_vote_segments import build_segments
        items = [parent]
        entries = {SEGMENT_ID: {"id": SEGMENT_ID, "date": THROUGH, "candidate": False}}
        root = Path(tempfile.mkdtemp(dir=self.root))
        build_segments(items, entries, [segment_review(**(review_changes or {}))], cache=cache or root,
                       collect=True, refresh=False, request=api)
        return items[0]["segments"][0]

    @staticmethod
    def parent(number=98, proposition="PL 1/2026", date_value=THROUGH):
        return {"id": VOTE_ID, "date": date_value, "proposition": proposition,
                "sources": {"rollCall": f"https://www.camara.leg.br/internet/votacao/mostraVotacao.asp?ideVotacao={number}"}}

    def test_amendment_voted_before_the_main_text_in_the_same_session_gets_a_note(self):
        segment = self.direct(self.parent(number=100), SegmentAPI())
        self.assertIn("antes da votação do texto principal", segment["dataNotes"][-1])
        with self.assertRaisesRegex(CollectionError, "outra votação principal"):
            self.direct(self.parent(number=100, date_value="2026-10-08"), SegmentAPI())

    def test_report_may_use_the_api_numbering_of_an_attached_bill(self):
        api = SegmentAPI()
        api.segment["proposicoesAfetadas"] = [{"id": 123, "siglaTipo": "PL", "numero": 1, "ano": 2026}]
        segment = self.direct(self.parent(proposition="PL 9/2025"), api)
        self.assertIn("numeração dos Dados Abertos (PL 1/2026)", segment["dataNotes"][-1])
        with self.assertRaisesRegex(CollectionError, "relatório não corresponde"):
            self.direct(self.parent(proposition="PL 9/2025"), SegmentAPI())

    def test_api_total_with_the_presiding_member_uses_the_report_total(self):
        report = segment_report().replace(b"<td>Deputado 3</td><td>SP</td><td>N\xc3\xa3o</td>",
                                          b"<td>Deputado 3</td><td>SP</td><td>N\xc3\xa3o</td></tr><tr><td>Deputado 4</td><td>SP</td><td>Artigo 17</td>")
        report = report.replace(b"Total ABC: 3", b"Total ABC: 4")
        api = SegmentAPI(report=report, description="Rejeitada a Emenda de Plenário nº 1. Sim: 1; Não: 2; Total: 4.")
        segment = self.direct(self.parent(), api)
        self.assertEqual(segment["tally"]["total"], 3)
        self.assertIn("quem presidiu", segment["dataNotes"][-1])

    def test_cache_can_follow_the_inventory_year_of_each_decision(self):
        root = Path(tempfile.mkdtemp(dir=self.root))
        segment = self.direct(self.parent(date_value="2025-12-01"), SegmentAPI(), cache=lambda identifier: root / identifier)
        self.assertEqual(segment["id"], SEGMENT_ID)
        self.assertTrue((root / SEGMENT_ID / "reports" / f"{SEGMENT_ID}.html").exists())

    def test_unconfirmed_segment_needs_a_reason_and_is_not_published(self):
        snapshot, _ = self.build([segment_review(status="pending", reason="texto ainda não conferido")])
        self.assertNotIn("segments", snapshot["items"][0])
        with self.assertRaisesRegex(CollectionError, "precisa de motivo"):
            self.build([segment_review(status="pending")])

    def test_review_without_meaning_or_evidence_is_rejected(self):
        with self.assertRaisesRegex(CollectionError, "incompleta"):
            self.build([segment_review(yesMeaning=" ")])
        with self.assertRaisesRegex(CollectionError, "incompleta"):
            self.build([segment_review(evidence={"method": "x", "object": "y"})])

    def test_merging_years_keeps_segment_details(self):
        part = self.build([segment_review()])
        snapshot, details = chamber_votes.merge_catalogues([part])
        self.assertIn(SEGMENT_ID, details)
        self.assertEqual(snapshot["coverage"]["segmentCount"], 1)


if __name__ == "__main__":
    unittest.main()
