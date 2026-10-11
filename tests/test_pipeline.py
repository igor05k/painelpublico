import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest import pipeline  # noqa: E402

YEAR = 2026


def document(deputies=5, senators=3, expenses_per_person=4, chamber_status='partial', senate_status='partial',
             roster_status='imported', period=f'{YEAR} (parcial, ano em andamento)'):
    """Documento no formato de ingest/legislative.py: listas oficiais e notas da cota."""
    sources = [
        {'id': 'camara_deputies_current', 'label': 'Câmara: lista', 'url': 'https://dadosabertos.camara.leg.br',
         'scope': 'lista', 'period': 'atual', 'status': roster_status, 'detail': '', 'fetchedAt': '2026-10-11T08:00:00+00:00'},
        {'id': 'camara_ceap', 'label': 'Câmara: CEAP', 'url': 'https://www.camara.leg.br/cotas', 'scope': 'cota',
         'period': period, 'status': chamber_status, 'detail': '', 'fetchedAt': '2026-10-11T08:00:00+00:00'},
        {'id': 'senado_senators_current', 'label': 'Senado: lista', 'url': 'https://legis.senado.leg.br',
         'scope': 'lista', 'period': 'atual', 'status': roster_status, 'detail': '', 'fetchedAt': '2026-10-11T08:00:00+00:00'},
        {'id': 'senado_ceaps', 'label': 'Senado: CEAPS', 'url': 'https://adm.senado.gov.br', 'scope': 'cota',
         'period': period, 'status': senate_status, 'detail': '', 'fetchedAt': '2026-10-11T08:00:00+00:00'},
    ]
    authorities, expenses = [], []
    for house, count, role, source in (('camara', deputies, 'deputado', 'camara_deputies_current'),
                                       ('senado', senators, 'senador', 'senado_senators_current')):
        for i in range(count):
            authorities.append({'id': f'{house}:{i}', 'name': f'Pessoa {house} {i}', 'role': role, 'sphere': 'federal',
                                'branch': 'legislativo', 'institution': house, 'uf': 'SP', 'sourceId': source})
            for month in range(1, expenses_per_person + 1):
                expenses.append({'id': f'{house}:{i}:{month}', 'authorityId': f'{house}:{i}',
                                 'sourceId': 'camara_ceap' if house == 'camara' else 'senado_ceaps',
                                 'year': YEAR, 'month': month, 'date': f'{YEAR}-{month:02d}-10', 'category': 'Escritório',
                                 'kind': 'reembolso', 'amount': 100 + i,
                                 'supplier': {'key': 'x', 'name': 'Empresa', 'cnpj': '12345678000199'}})
    return {'sources': sources, 'authorities': authorities, 'expenses': expenses}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mail_environ = {'PAINEL_MAIL_TO': 'a@x.br', 'PAINEL_SMTP_HOST': 'smtp.x.br'}
        self.config = pipeline.PipelineConfig(data_dir=self.root / 'data', db_path=self.root / 'data' / 'live.sqlite3',
                                              year=YEAR, environ=dict(self.mail_environ))
        self.sent = []
        self.collector_exit = 0
        self.next_document = document()

    def tearDown(self):
        self.temp.cleanup()

    # O coletor real faz rede; aqui ele grava o documento preparado e devolve o código combinado.
    def fake_collector(self, config):
        config.document_path.parent.mkdir(parents=True, exist_ok=True)
        config.document_path.write_text(json.dumps(self.next_document), encoding='utf-8')
        return subprocess.CompletedProcess(['legislative'], self.collector_exit, stdout='{}', stderr='')

    def fake_mail(self, mail, subject, body):
        self.sent.append((mail, subject, body))

    def run_daily(self, config=None):
        with mock.patch.object(pipeline, 'run_collector', self.fake_collector), redirect_stdout(StringIO()):
            return pipeline.run_daily(config or self.config, mail_sender=self.fake_mail)

    def counts(self):
        with closing(sqlite3.connect(self.config.db_path)) as db:
            roster = db.execute('SELECT COUNT(*) FROM roster').fetchone()[0]
            expenses = db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0]
        return roster, expenses

    def test_first_run_creates_database_status_and_no_mail_on_success(self):
        status = self.run_daily()
        self.assertEqual(status['result'], 'ok', status)
        self.assertEqual(self.counts(), (8, 32))
        self.assertEqual([s['name'] for s in status['steps']],
                         ['collect', 'validate', 'backup', 'stage', 'import', 'verify', 'publish', 'notify'])
        self.assertEqual(status['summary']['roster'], {'camara_deputies_current': 5, 'senado_senators_current': 3})
        self.assertEqual(json.loads(self.config.status_path.read_text())['result'], 'ok')
        self.assertEqual(len(self.config.history_path.read_text().splitlines()), 1)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.config.work_db.exists())
        self.assertEqual(list(self.config.backups_dir.glob('*.sqlite3')) if self.config.backups_dir.exists() else [], [])

    def test_second_run_backs_up_prunes_and_updates_in_place(self):
        self.run_daily()
        self.next_document = document(expenses_per_person=5)
        config = pipeline.PipelineConfig(**{**self.config.__dict__, 'keep_backups': 1})
        self.run_daily(config)
        self.assertEqual(self.counts(), (8, 40))
        backups = list(self.config.backups_dir.glob('na-lupa-daily-*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0], 32)
        self.run_daily(config)
        self.assertEqual(len(list(self.config.backups_dir.glob('na-lupa-daily-*.sqlite3'))), 1)

    def test_roster_drop_is_refused_and_live_database_is_kept(self):
        self.run_daily()
        self.next_document = document(deputies=2)
        status = self.run_daily()
        self.assertEqual(status['result'], 'failed')
        self.assertIn('camara_deputies_current caiu de 5 para 2', status['error'])
        self.assertEqual(self.counts(), (8, 32))
        self.assertEqual(len(self.sent), 1)
        self.assertIn('FALHOU', self.sent[0][1])
        self.assertIn('Regressão detectada', self.sent[0][2])
        self.assertFalse(self.config.work_db.exists())

    def test_expense_drop_is_refused_but_unavailable_source_keeps_previous_rows(self):
        self.run_daily()
        self.next_document = document(expenses_per_person=2)
        self.assertEqual(self.run_daily()['result'], 'failed')
        self.assertEqual(self.counts(), (8, 32))
        self.sent.clear()
        # Fonte indisponível: a importação preserva as notas anteriores e a execução fica parcial, com aviso.
        unavailable = document(expenses_per_person=4, senate_status='unavailable')
        unavailable['expenses'] = [e for e in unavailable['expenses'] if e['sourceId'] != 'senado_ceaps']
        self.next_document, self.collector_exit = unavailable, 1
        status = self.run_daily()
        self.assertEqual(status['result'], 'partial')
        self.assertEqual(self.counts(), (8, 32))
        self.assertEqual(len(self.sent), 1)
        self.assertIn('parcial', self.sent[0][1])
        self.assertIn('senado_ceaps', self.sent[0][2])

    def test_document_of_another_year_is_not_imported(self):
        self.run_daily()
        self.next_document = document(period='2025')
        status = self.run_daily()
        self.assertEqual(status['result'], 'failed')
        self.assertIn('2025', status['error'])
        self.assertEqual([s['name'] for s in status['steps'] if s['status'] == 'failed'], ['validate'])
        self.assertEqual(self.counts(), (8, 32))

    def test_collector_crash_and_missing_document_fail_before_import(self):
        self.collector_exit = 2
        status = self.run_daily()
        self.assertEqual(status['result'], 'failed')
        self.assertIn('código 2', status['error'])
        self.assertFalse(self.config.db_path.exists())

    def test_dry_run_leaves_published_database_untouched(self):
        self.run_daily()
        self.next_document = document(expenses_per_person=5)
        status = self.run_daily(pipeline.PipelineConfig(**{**self.config.__dict__, 'dry_run': True}))
        self.assertEqual(status['result'], 'ok')
        self.assertEqual(self.counts(), (8, 32))
        self.assertIn('dry-run', status['steps'][-2]['skipped'])

    def test_pending_journal_blocks_publication(self):
        self.run_daily()
        journal = Path(str(self.config.db_path) + '-journal')
        journal.write_bytes(b'')
        status = self.run_daily()
        self.assertEqual(status['result'], 'failed')
        self.assertIn('journal', status['error'])

    def test_concurrent_run_is_refused(self):
        with pipeline.Lock(self.config.lock_path):
            status = self.run_daily()
        self.assertEqual(status['result'], 'failed')
        self.assertIn('em andamento', status['error'])
        self.assertEqual(status['steps'], [{**status['steps'][0]}])  # só o registro de aviso

    def test_mail_config_and_report(self):
        self.assertIsNone(pipeline.MailConfig.from_environ({}))
        mail = pipeline.MailConfig.from_environ({'PAINEL_MAIL_TO': 'a@x.br, b@x.br', 'PAINEL_SMTP_HOST': 'smtp.x.br',
                                                 'PAINEL_SMTP_PORT': '465', 'PAINEL_SMTP_SECURITY': 'SSL',
                                                 'PAINEL_SMTP_USER': 'u', 'PAINEL_SMTP_PASSWORD': 'p',
                                                 'PAINEL_MAIL_ON_SUCCESS': '1'})
        self.assertEqual((mail.to, mail.sender, mail.port, mail.security, mail.on_success),
                         (['a@x.br', 'b@x.br'], 'u', 465, 'ssl', True))
        self.config.environ['PAINEL_MAIL_ON_SUCCESS'] = 'sim'
        status = self.run_daily()
        self.assertEqual(status['result'], 'ok')
        self.assertEqual(len(self.sent), 1)
        subject, body = self.sent[0][1], self.sent[0][2]
        self.assertTrue(subject.startswith('[Painel Público] Atualização diária concluída em '), subject)
        self.assertIn('lista camara_deputies_current: 5', body)
        self.assertIn('notas senado_ceaps: 12', body)
        self.assertIn('publish: ok', body)

    def test_mail_failure_is_recorded_without_hiding_the_result(self):
        def broken(mail, subject, body):
            raise OSError('smtp down')
        self.next_document = document(deputies=0, roster_status='unavailable')
        with mock.patch.object(pipeline, 'run_collector', self.fake_collector), redirect_stdout(StringIO()):
            status = pipeline.run_daily(self.config, mail_sender=broken)
        notify = status['steps'][-1]
        self.assertEqual(notify['name'], 'notify')
        self.assertEqual(notify['status'], 'failed')
        self.assertIn('smtp down', notify['mail'])

    def test_notify_failure_uses_last_status(self):
        self.next_document = document(period='2025')
        self.run_daily()
        code = pipeline.notify_failure(self.config, 'painel-ingest.service', mail_sender=self.fake_mail)
        self.assertEqual(code, 0)
        self.assertIn('painel-ingest.service falhou', self.sent[-1][1])
        self.assertIn('2025', self.sent[-1][2])

    def test_cli_status_reports_last_run(self):
        self.run_daily()
        out = StringIO()
        with redirect_stdout(out):
            code = pipeline.main(['--db', str(self.config.db_path), '--data-dir', str(self.config.data_dir), 'status'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())['result'], 'ok')


if __name__ == '__main__':
    unittest.main()
