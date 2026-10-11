"""Orquestrador das atualizações automáticas.

O comando ``daily`` executa a atualização diária da cota (Câmara e Senado) do ano corrente:
coleta, importa em uma cópia de trabalho do banco, verifica integridade e regressão, publica a
cópia por troca atômica e avisa por e-mail. Cada etapa fica registrada em ``data/status/``.

Regras do orquestrador:

- uma execução por vez (lock em ``data/status/pipeline.lock``);
- o banco em uso nunca recebe escrita direta: a importação acontece em ``data/pipeline/`` e só
  substitui o banco publicado depois de passar nas verificações;
- uma coleta indisponível preserva a fotografia anterior (regra já existente da importação);
- uma queda acima do limite na lista oficial ou nas notas não é publicada;
- falha ou resultado parcial gera aviso por e-mail quando o SMTP está configurado.

Uso:
    python3 -m ingest.pipeline daily [--dry-run] [--year AAAA]
    python3 -m ingest.pipeline status
    python3 -m ingest.pipeline test-mail
    python3 -m ingest.pipeline notify-failure --unit painel-ingest.service
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import json
import os
import shutil
import smtplib
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.request
from contextlib import closing
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import DB_PATH, ROSTER_SOURCES  # noqa: E402
from backend.database import backup_database, check_database  # noqa: E402
from backend.public_store import import_documents  # noqa: E402

QUOTA_SOURCES = ("camara_ceap", "senado_ceaps")
DAILY_BACKUP_PREFIX = "na-lupa-daily-"
COLLECTOR_TIMEOUT_SECONDS = 1800
MAIL_SUBJECT_PREFIX = "[Painel Público]"
RESULT_LABELS = {"ok": "concluída", "partial": "parcial", "failed": "FALHOU"}


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def log(message: str) -> None:
    print(f"{utc_now().strftime('%H:%M:%S')} {message}", flush=True)


class PipelineError(RuntimeError):
    """Falha que interrompe a execução antes de publicar."""


@dataclass
class PipelineConfig:
    data_dir: Path = ROOT / "data"
    db_path: Path = DB_PATH
    year: int = field(default_factory=lambda: utc_now().year)
    dry_run: bool = False
    keep_backups: int = 7
    max_roster_drop: float = 0.05
    max_expense_drop: float = 0.10
    python: str = sys.executable
    environ: dict = field(default_factory=lambda: dict(os.environ))

    @property
    def status_dir(self) -> Path:
        return self.data_dir / "status"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "pipeline"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def document_path(self) -> Path:
        return self.data_dir / "imports" / "legislative.json"

    @property
    def work_db(self) -> Path:
        return self.work_dir / "na-lupa.work.sqlite3"

    @property
    def lock_path(self) -> Path:
        return self.status_dir / "pipeline.lock"

    @property
    def status_path(self) -> Path:
        return self.status_dir / "daily.json"

    @property
    def history_path(self) -> Path:
        return self.status_dir / "daily-history.jsonl"


class Run:
    """Registro de uma execução: etapas, resultado e gravação atômica do status."""

    def __init__(self, config: PipelineConfig, job: str = "daily"):
        self.config = config
        self.job = job
        self.started = utc_now()
        self.steps: list[dict] = []
        self.result = "ok"
        self.error: str | None = None
        self.summary: dict = {}

    def step(self, name: str):
        return _Step(self, name)

    def downgrade(self, result: str) -> None:
        order = ("ok", "partial", "failed")
        if order.index(result) > order.index(self.result):
            self.result = result

    def to_dict(self) -> dict:
        finished = utc_now()
        return {
            "job": self.job,
            "result": self.result,
            "year": self.config.year,
            "dryRun": self.config.dry_run,
            "startedAt": self.started.isoformat(timespec="seconds"),
            "finishedAt": finished.isoformat(timespec="seconds"),
            "seconds": round((finished - self.started).total_seconds(), 1),
            "database": str(self.config.db_path),
            "error": self.error,
            "summary": self.summary,
            "steps": self.steps,
        }

    def write(self, history: bool = False) -> dict:
        """Grava data/status/daily.json; com ``history``, acrescenta uma linha ao histórico."""
        payload = self.to_dict()
        self.config.status_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.config.status_path, payload)
        if history:
            with self.config.history_path.open("a", encoding="utf-8") as handle:
                compact = {key: payload[key] for key in ("job", "result", "startedAt", "finishedAt", "seconds", "error")}
                compact["summary"] = payload["summary"]
                handle.write(json.dumps(compact, ensure_ascii=False) + "\n")
        return payload


class _Step:
    def __init__(self, run: Run, name: str):
        self.run = run
        self.record = {"name": name, "status": "running", "startedAt": utc_now().isoformat(timespec="seconds")}
        self.run.steps.append(self.record)
        self.clock = time.monotonic()

    def __enter__(self):
        log(f"[{self.record['name']}] início")
        return self

    def detail(self, **values) -> None:
        self.record.update(values)

    def partial(self, message: str) -> None:
        self.record["status"] = "partial"
        self.record["message"] = message
        self.run.downgrade("partial")

    def __exit__(self, exc_type, exc, _tb):
        self.record["seconds"] = round(time.monotonic() - self.clock, 1)
        self.record["finishedAt"] = utc_now().isoformat(timespec="seconds")
        if exc is not None:
            self.record["status"] = "failed"
            self.record["message"] = f"{type(exc).__name__}: {exc}"
            self.run.downgrade("failed")
            log(f"[{self.record['name']}] falhou: {exc}")
            return False
        if self.record["status"] == "running":
            self.record["status"] = "ok"
        log(f"[{self.record['name']}] {self.record['status']} em {self.record['seconds']}s")
        return False


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


# ---- Lock -------------------------------------------------------------------------------------

class Lock:
    """Lock de arquivo não bloqueante; uma segunda execução simultânea é recusada."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            self.handle = None
            raise PipelineError(
                f"Outra execução do pipeline está em andamento (lock em {self.path})."
            ) from error
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(f"{os.getpid()} {utc_now().isoformat(timespec='seconds')}\n")
        self.handle.flush()
        return self

    def __exit__(self, *_exc):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None
        return False


# ---- Etapas -----------------------------------------------------------------------------------

def run_collector(config: PipelineConfig) -> subprocess.CompletedProcess:
    """Executa o coletor da cota em subprocesso; substituível nos testes."""
    command = [
        config.python, str(ROOT / "ingest" / "legislative.py"),
        "--year", str(config.year), "--output", str(config.document_path),
    ]
    log("coleta: " + " ".join(command[1:]))
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=COLLECTOR_TIMEOUT_SECONDS,
        env={**config.environ, "PYTHONUNBUFFERED": "1"},
    )


def collect(run: Run) -> None:
    config = run.config
    with run.step("collect") as step:
        config.document_path.parent.mkdir(parents=True, exist_ok=True)
        before = config.document_path.stat().st_mtime_ns if config.document_path.exists() else None
        try:
            completed = run_collector(config)
        except subprocess.TimeoutExpired as error:
            raise PipelineError(f"Coleta excedeu {COLLECTOR_TIMEOUT_SECONDS}s.") from error
        stderr_tail = (completed.stderr or "").strip().splitlines()[-5:]
        step.detail(exitCode=completed.returncode, stderrTail=stderr_tail)
        if completed.returncode not in (0, 1):
            raise PipelineError(f"Coletor terminou com código {completed.returncode}: {' | '.join(stderr_tail)}")
        after = config.document_path.stat().st_mtime_ns if config.document_path.exists() else None
        if after is None or after == before:
            raise PipelineError("O coletor não gravou um documento novo em " + str(config.document_path))
        if completed.returncode == 1:
            step.partial("Ao menos uma fonte ficou indisponível; a fotografia anterior dessa fonte é preservada.")


def validate_document(run: Run) -> dict:
    """Confere o documento antes de importar: fontes, ano esperado e o que será substituído."""
    config = run.config
    with run.step("validate") as step:
        try:
            payload = json.loads(config.document_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PipelineError(f"Documento de importação ilegível: {error}") from error
        sources = {s.get("id"): s for s in payload.get("sources", []) if isinstance(s, dict)}
        if not sources:
            raise PipelineError("Documento sem fontes.")
        statuses = {sid: s.get("status") for sid, s in sources.items()}
        step.detail(sources=statuses)
        for source_id in QUOTA_SOURCES:
            source = sources.get(source_id)
            if source is None:
                raise PipelineError(f"Fonte {source_id} ausente do documento.")
            period = str(source.get("period") or "")
            if source.get("status") in ("imported", "partial") and not period.startswith(str(config.year)):
                raise PipelineError(
                    f"Fonte {source_id} cobre o período '{period}', não {config.year}; "
                    "importar substituiria as notas do ano corrente."
                )
        usable = [sid for sid, status in statuses.items() if status in ("imported", "partial")]
        if not usable:
            raise PipelineError("Nenhuma fonte disponível nesta coleta; nada a importar.")
        unavailable = [sid for sid, status in statuses.items() if status == "unavailable"]
        if unavailable:
            step.partial("Fontes indisponíveis: " + ", ".join(unavailable))
        step.detail(authorities=len(payload.get("authorities", [])), expenses=len(payload.get("expenses", [])))
        return payload


def backup(run: Run) -> Path | None:
    config = run.config
    with run.step("backup") as step:
        if not config.db_path.is_file():
            step.detail(skipped="banco publicado ainda não existe")
            return None
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        target = config.backups_dir / f"{DAILY_BACKUP_PREFIX}{stamp}.sqlite3"
        suffix = 1
        while target.exists():
            target = config.backups_dir / f"{DAILY_BACKUP_PREFIX}{stamp}-{suffix}.sqlite3"
            suffix += 1
        destination = backup_database(config.db_path, target)
        removed = prune_backups(config.backups_dir, config.keep_backups)
        step.detail(backup=str(destination), removed=[p.name for p in removed])
        return destination


def prune_backups(directory: Path, keep: int) -> list[Path]:
    """Mantém só os ``keep`` backups diários mais recentes; backups manuais não são tocados."""
    candidates = sorted(directory.glob(f"{DAILY_BACKUP_PREFIX}*.sqlite3"))
    removed = []
    for path in candidates[: max(0, len(candidates) - keep)]:
        path.unlink()
        removed.append(path)
    return removed


def stage(run: Run) -> None:
    """Copia o banco publicado para a área de trabalho; a importação nunca toca o banco em uso."""
    config = run.config
    with run.step("stage") as step:
        config.work_dir.mkdir(parents=True, exist_ok=True)
        for leftover in config.work_dir.glob(config.work_db.name + "*"):
            leftover.unlink()
        if config.db_path.is_file():
            backup_database(config.db_path, config.work_db)
            step.detail(source=str(config.db_path))
        else:
            step.detail(source=None, note="banco novo será criado pela importação")


def import_into_work(run: Run) -> dict:
    config = run.config
    with run.step("import") as step:
        counts = import_documents([config.document_path], config.work_db)
        step.detail(imported=counts)
        return counts


def _counts(db_path: Path) -> dict:
    """Contagens usadas no guarda de regressão; banco ausente conta como vazio."""
    result = {"roster": {sid: 0 for sid in ROSTER_SOURCES}, "expenses": {sid: 0 for sid in QUOTA_SOURCES},
              "authorities": 0, "snapshotAt": None}
    if not Path(db_path).is_file():
        return result
    with closing(sqlite3.connect(db_path, timeout=30)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        if "roster" in tables:
            for sid in ROSTER_SOURCES:
                result["roster"][sid] = db.execute("SELECT COUNT(*) FROM roster WHERE sourceId=?", (sid,)).fetchone()[0]
        if "expenses" in tables:
            for sid in QUOTA_SOURCES:
                result["expenses"][sid] = db.execute("SELECT COUNT(*) FROM expenses WHERE sourceId=?", (sid,)).fetchone()[0]
        if "authorities" in tables:
            result["authorities"] = db.execute("SELECT COUNT(*) FROM authorities").fetchone()[0]
        if "meta" in tables:
            row = db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
            result["snapshotAt"] = row[0] if row else None
    return result


def regression_problems(before: dict, after: dict, config: PipelineConfig, statuses: dict) -> list[str]:
    """Quedas acima do limite não são publicadas; fontes indisponíveis mantêm o valor anterior e passam."""
    problems = []
    for sid in ROSTER_SOURCES:
        old, new = before["roster"][sid], after["roster"][sid]
        if statuses.get(sid) != "imported":
            continue
        if new == 0 and old > 0:
            problems.append(f"lista {sid} ficou vazia (antes {old})")
        elif old and (old - new) / old > config.max_roster_drop:
            problems.append(f"lista {sid} caiu de {old} para {new} (limite {config.max_roster_drop:.0%})")
    for sid in QUOTA_SOURCES:
        old, new = before["expenses"][sid], after["expenses"][sid]
        if statuses.get(sid) not in ("imported", "partial"):
            continue
        if old and (old - new) / old > config.max_expense_drop:
            problems.append(f"notas {sid} caíram de {old} para {new} (limite {config.max_expense_drop:.0%})")
    return problems


def verify(run: Run, statuses: dict) -> dict:
    config = run.config
    with run.step("verify") as step:
        check = check_database(config.work_db)
        step.detail(check={k: check[k] for k in ("ok", "schemaVersion", "quickCheck", "missingTables")},
                    foreignKeyErrors=len(check.get("foreignKeyErrors") or []))
        if not check["ok"]:
            raise PipelineError("O banco de trabalho não passou na verificação de integridade.")
        before, after = _counts(config.db_path), _counts(config.work_db)
        step.detail(before=before, after=after)
        problems = regression_problems(before, after, config, statuses)
        if problems:
            raise PipelineError("Regressão detectada, publicação recusada: " + "; ".join(problems))
        run.summary.update({
            "roster": after["roster"], "expenses": after["expenses"],
            "snapshotAt": after["snapshotAt"], "previousSnapshotAt": before["snapshotAt"],
        })
        return after


def publish(run: Run) -> None:
    """Troca o banco publicado pela cópia verificada em uma única operação do sistema de arquivos."""
    config = run.config
    with run.step("publish") as step:
        if config.dry_run:
            step.detail(skipped="dry-run: banco publicado não foi alterado")
            return
        for suffix in ("-journal", "-wal", "-shm"):
            if Path(str(config.db_path) + suffix).exists():
                raise PipelineError(
                    f"Existe {config.db_path.name}{suffix} ao lado do banco publicado: há escrita em andamento "
                    "ou um journal pendente. Publicação recusada."
                )
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        _replace_file(config.work_db, config.db_path)
        step.detail(published=str(config.db_path))


def _replace_file(source: Path, destination: Path) -> None:
    """``os.replace`` atômico; em sistemas de arquivos diferentes, copia ao lado e então troca."""
    try:
        os.replace(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        staging = destination.with_name(destination.name + ".new")
        shutil.copyfile(source, staging)
        os.replace(staging, destination)
        source.unlink()


def cleanup(config: PipelineConfig) -> None:
    for leftover in config.work_dir.glob(config.work_db.name + "*"):
        try:
            leftover.unlink()
        except OSError:
            pass


# ---- Aviso por e-mail -------------------------------------------------------------------------

@dataclass
class MailConfig:
    to: list[str]
    sender: str
    host: str
    port: int = 587
    user: str | None = None
    password: str | None = None
    security: str = "starttls"
    on_success: bool = False

    @classmethod
    def from_environ(cls, environ: dict) -> "MailConfig | None":
        to = [item.strip() for item in (environ.get("PAINEL_MAIL_TO") or "").split(",") if item.strip()]
        host = environ.get("PAINEL_SMTP_HOST")
        if not to or not host:
            return None
        return cls(
            to=to,
            sender=environ.get("PAINEL_MAIL_FROM") or environ.get("PAINEL_SMTP_USER") or to[0],
            host=host,
            port=int(environ.get("PAINEL_SMTP_PORT") or 587),
            user=environ.get("PAINEL_SMTP_USER") or None,
            password=environ.get("PAINEL_SMTP_PASSWORD") or None,
            security=(environ.get("PAINEL_SMTP_SECURITY") or "starttls").lower(),
            on_success=(environ.get("PAINEL_MAIL_ON_SUCCESS") or "").lower() in ("1", "true", "yes", "sim"),
        )


def send_mail(config: MailConfig, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = ", ".join(config.to)
    message["Subject"] = subject
    message.set_content(body)
    if config.security == "ssl":
        client = smtplib.SMTP_SSL(config.host, config.port, timeout=30)
    else:
        client = smtplib.SMTP(config.host, config.port, timeout=30)
    with client:
        if config.security == "starttls":
            client.starttls()
        if config.user:
            client.login(config.user, config.password or "")
        client.send_message(message)


def compose_report(status: dict) -> tuple[str, str]:
    """Assunto e corpo em texto puro, legíveis no celular."""
    label = RESULT_LABELS.get(status["result"], status["result"])
    day = status["startedAt"][:10]
    subject = f"{MAIL_SUBJECT_PREFIX} Atualização diária {label} em {day}"
    lines = [
        f"Resultado: {label}",
        f"Início: {status['startedAt']}   Fim: {status['finishedAt']}   Duração: {status['seconds']}s",
        f"Banco: {status['database']}",
    ]
    if status.get("dryRun"):
        lines.append("Modo dry-run: o banco publicado não foi alterado.")
    if status.get("error"):
        lines += ["", "Erro:", status["error"]]
    summary = status.get("summary") or {}
    if summary:
        lines += ["", "Fotografia:"]
        for sid, count in (summary.get("roster") or {}).items():
            lines.append(f"  lista {sid}: {count}")
        for sid, count in (summary.get("expenses") or {}).items():
            lines.append(f"  notas {sid}: {count}")
        if summary.get("snapshotAt"):
            lines.append(f"  snapshotAt: {summary['snapshotAt']} (anterior: {summary.get('previousSnapshotAt')})")
    lines += ["", "Etapas:"]
    for step in status.get("steps", []):
        line = f"  {step['name']}: {step['status']} ({step.get('seconds', '?')}s)"
        if step.get("message"):
            line += f" — {step['message']}"
        lines.append(line)
        if step.get("sources"):
            lines.append("    fontes: " + ", ".join(f"{k}={v}" for k, v in step["sources"].items()))
    lines += ["", "Status completo: data/status/daily.json no servidor."]
    return subject, "\n".join(lines) + "\n"


def notify(run: Run, status: dict, mail_sender=send_mail) -> None:
    """Avisa por e-mail (falha e parcial sempre; sucesso se PAINEL_MAIL_ON_SUCCESS) e faz o ping opcional."""
    config = run.config
    record = {"name": "notify", "status": "ok", "startedAt": utc_now().isoformat(timespec="seconds")}
    mail = MailConfig.from_environ(config.environ)
    should_mail = status["result"] != "ok" or (mail is not None and mail.on_success)
    if mail is None:
        record["mail"] = "não configurado (PAINEL_MAIL_TO e PAINEL_SMTP_HOST)"
        if status["result"] != "ok":
            log("aviso: SMTP não configurado; a falha fica só no status e no journal")
    elif should_mail:
        subject, body = compose_report(status)
        try:
            mail_sender(mail, subject, body)
            record["mail"] = f"enviado para {', '.join(mail.to)}"
        except (OSError, smtplib.SMTPException) as error:
            record["mail"] = f"falha no envio: {type(error).__name__}: {error}"
            record["status"] = "failed"
            log(record["mail"])
    else:
        record["mail"] = "sucesso sem aviso (PAINEL_MAIL_ON_SUCCESS desligado)"
    ping_url = config.environ.get("PAINEL_HEALTHCHECK_URL")
    if ping_url:
        record["ping"] = ping(ping_url if status["result"] == "ok" else ping_url.rstrip("/") + "/fail")
    record["finishedAt"] = utc_now().isoformat(timespec="seconds")
    run.steps.append(record)
    log(f"[notify] {record['mail']}")


def ping(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return f"{url}: {response.status}"
    except OSError as error:
        return f"{url}: falha ({error})"


# ---- Execução ---------------------------------------------------------------------------------

def run_daily(config: PipelineConfig, mail_sender=send_mail) -> dict:
    """Executa a atualização diária e devolve o status gravado. Nunca levanta exceção por falha de etapa."""
    run = Run(config)
    log(f"atualização diária de {config.year}" + (" (dry-run)" if config.dry_run else ""))
    try:
        with Lock(config.lock_path):
            try:
                collect(run)
                payload = validate_document(run)
                statuses = {s["id"]: s.get("status") for s in payload["sources"]}
                backup(run)
                stage(run)
                import_into_work(run)
                verify(run, statuses)
                publish(run)
            finally:
                cleanup(config)
    except PipelineError as error:
        run.error = str(error)
        run.downgrade("failed")
    except Exception as error:  # noqa: BLE001 - qualquer falha inesperada vira status e aviso
        run.error = f"{type(error).__name__}: {error}\n{traceback.format_exc()}"
        run.downgrade("failed")
    status = run.write()
    notify(run, status, mail_sender=mail_sender)
    status = run.write(history=True)
    log(f"resultado: {RESULT_LABELS.get(status['result'], status['result'])}")
    return status


def read_status(config: PipelineConfig) -> dict | None:
    if not config.status_path.is_file():
        return None
    return json.loads(config.status_path.read_text(encoding="utf-8"))


def notify_failure(config: PipelineConfig, unit: str, mail_sender=send_mail) -> int:
    """Chamado pelo systemd (OnFailure) quando a unidade termina sem gravar status: aviso de último recurso."""
    mail = MailConfig.from_environ(config.environ)
    status = read_status(config)
    lines = [f"A unidade {unit} terminou com falha.", ""]
    if status:
        lines += [f"Último status gravado: {status['result']} em {status['finishedAt']} (job {status['job']})."]
        if status.get("error"):
            lines += ["", status["error"]]
    else:
        lines.append("Nenhum status gravado em data/status/daily.json.")
    lines += ["", f"Veja: journalctl -u {unit} -n 100"]
    if mail is None:
        print("\n".join(lines))
        print("SMTP não configurado; aviso impresso apenas no journal.", file=sys.stderr)
        return 1
    mail_sender(mail, f"{MAIL_SUBJECT_PREFIX} {unit} falhou", "\n".join(lines) + "\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DB_PATH, help="banco publicado (padrão: PAINEL_DB)")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="raiz de imports/, backups/, status/")
    commands = parser.add_subparsers(dest="command", required=True)
    daily = commands.add_parser("daily", help="coleta e importa a cota do ano corrente")
    daily.add_argument("--year", type=int, default=None)
    daily.add_argument("--dry-run", action="store_true", help="faz tudo, menos substituir o banco publicado")
    daily.add_argument("--keep-backups", type=int, default=7)
    daily.add_argument("--max-roster-drop", type=float, default=0.05)
    daily.add_argument("--max-expense-drop", type=float, default=0.10)
    commands.add_parser("status", help="imprime o último status gravado")
    commands.add_parser("test-mail", help="envia um e-mail de teste com a configuração atual")
    failure = commands.add_parser("notify-failure", help="aviso de último recurso, usado pelo systemd OnFailure")
    failure.add_argument("--unit", default="painel-ingest.service")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    data_dir = args.data_dir if args.data_dir.is_absolute() else ROOT / args.data_dir
    db_path = args.db if args.db.is_absolute() else ROOT / args.db
    if args.command == "daily":
        config = PipelineConfig(
            data_dir=data_dir, db_path=db_path, year=args.year or utc_now().year, dry_run=args.dry_run,
            keep_backups=args.keep_backups, max_roster_drop=args.max_roster_drop,
            max_expense_drop=args.max_expense_drop,
        )
        status = run_daily(config)
        return 0 if status["result"] == "ok" else 1
    config = PipelineConfig(data_dir=data_dir, db_path=db_path)
    if args.command == "status":
        status = read_status(config)
        if status is None:
            print(json.dumps({"status": "nunca executado", "path": str(config.status_path)}, ensure_ascii=False))
            return 1
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status["result"] == "ok" else 1
    if args.command == "test-mail":
        mail = MailConfig.from_environ(config.environ)
        if mail is None:
            print("Defina PAINEL_MAIL_TO e PAINEL_SMTP_HOST (ver deploy/pipeline.env.example).", file=sys.stderr)
            return 1
        send_mail(mail, f"{MAIL_SUBJECT_PREFIX} Teste de aviso", "Se você recebeu esta mensagem, o aviso por e-mail está configurado.\n")
        print(f"E-mail de teste enviado para {', '.join(mail.to)} via {mail.host}:{mail.port}")
        return 0
    return notify_failure(config, args.unit)


if __name__ == "__main__":
    raise SystemExit(main())
