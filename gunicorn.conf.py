import multiprocessing
import os
import shutil

from prometheus_flask_exporter.multiprocess import GunicornInternalPrometheusMetrics

bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))

# gthread, nao sync: com workers sync, uma verificacao de prontidao contra um
# banco pendurado ocupa o worker inteiro, e com todos ocupados /health deixa de
# ser respondido - convertendo falha de dependencia em falha de vivacidade
# (PRD-0001 - I7, design D4). Threads compartilham memoria e a espera aqui e
# I/O puro no socket do Postgres, que libera o GIL.
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", 4))
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

reload = os.getenv("GUNICORN_RELOAD", "false").lower() == "true"
reload_engine = "poll"


def on_starting(server):
    multiproc_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR", "/tmp/prometheus_multiproc")
    shutil.rmtree(multiproc_dir, ignore_errors=True)
    os.makedirs(multiproc_dir, exist_ok=True)


def child_exit(server, worker):
    GunicornInternalPrometheusMetrics.mark_process_dead_on_child_exit(worker.pid)
