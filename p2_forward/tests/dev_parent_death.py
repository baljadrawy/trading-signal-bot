"""Helper: start a ProcessCertifier, print the child pid, then die abruptly (parent-death test)."""
import os, sys, tempfile, time
from p2_forward import writer as Wm
from p2_forward.certproc import ProcessCertifier
if __name__ == "__main__":
    d = tempfile.mkdtemp()
    c = ProcessCertifier(d, "d" * 32, Wm.new_stats(), lambda: None); c.start(); c.wait_ready(10)
    print(c.ident, flush=True); os._exit(0)
