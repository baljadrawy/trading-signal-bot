"""`python -m stress fakex|collector` (a package __main__, so multiprocessing spawn never re-imports it)."""
import os
import sys

if sys.argv[1:2] == ["fakex"]:
    from .fakex import serve
    serve(os.environ["STRESS_TLS_CERT"], os.environ["STRESS_TLS_KEY"], int(os.environ.get("STRESS_FAKEX_PORT", "8443")),
          os.path.join(os.environ.get("STRESS_OUT", "/out"), "fakex_stats.jsonl"))
elif sys.argv[1:2] == ["collector"]:
    from .harness import run
    sys.exit(run())
else:
    sys.exit("usage: python -m stress fakex|collector")
