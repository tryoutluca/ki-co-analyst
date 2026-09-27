"""
backend/job_stdout.py — Leitet print()-Ausgaben an den Progress des richtigen Jobs.

Einmal global als sys.stdout installiert statt pro Job ersetzt: vorher landeten
bei zwei parallelen Analysen die Logs von Job A in Job B, und das Wiederherstellen
setzte ggf. den Capture des anderen Jobs als stdout.
"""
import threading


class JobStdout:
    """Zuordnung per Thread-lokaler Job-ID. Worker-Threads der Agenten
    (ThreadPoolExecutor) haben keine — ihre Ausgaben gehen an den Job, wenn
    genau einer läuft, sonst an den ursprünglichen stdout."""

    def __init__(self, original, jobs: dict, lock: threading.Lock):
        self._original = original
        self._jobs = jobs
        self._lock = lock
        self._local = threading.local()

    def bind(self, job_id: str | None):
        self._local.job_id = job_id

    def _target_job(self) -> str | None:
        jid = getattr(self._local, "job_id", None)
        if jid:
            return jid
        # "cancelling" zählt mit: ein abgebrochener Job beendet seinen laufenden
        # Agenten noch — dessen Worker-Logs dürfen nicht in einen neuen Job fallen
        with self._lock:
            active = [k for k, j in self._jobs.items() if j.get("status") in ("running", "cancelling")]
        return active[0] if len(active) == 1 else None

    def write(self, text: str):
        jid = self._target_job()
        if jid is None:
            return self._original.write(text)
        line = text.strip()
        if line:
            with self._lock:
                if jid in self._jobs:
                    self._jobs[jid]["progress"].append(line)
        return len(text)

    def flush(self):
        self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)
