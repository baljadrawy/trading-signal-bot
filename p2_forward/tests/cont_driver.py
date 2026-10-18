"""Subprocess driver for crash tests: a continuous collector on the offline fake exchange with a GIVEN calendar.
python -m tests.cont_driver <data_dir> <calendar_json> <seconds> [config_overrides_json]"""
import asyncio
import contextlib
import datetime as dt
import io
import json
import os
import sys
from unittest import mock

from p2_forward import app as A, cal, config as C


def main():
    d, calp, seconds = sys.argv[1], json.loads(sys.argv[2]), float(sys.argv[3])
    over = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
    cal.configure(calp["hour_ms"], calp["epoch_hour"], dt.datetime.fromisoformat(calp["base"]))
    from tests.test_p2cr_continuous import UniverseShiftExchange, cont_cfg
    from tests.test_verify_independent import ENV
    cfg = cont_cfg(d, **over); C.validate(cfg)
    try:
        c = A.Collector(cfg)
    except A.StartupRefused as e:
        print("REFUSED", e, flush=True); return A.EXIT_STARTUP
    s = UniverseShiftExchange(); c.session_factory = lambda: s

    async def go():
        asyncio.get_running_loop().call_later(seconds, c._signal_stop)
        return await c.run()
    print("BOOT", c.boot_id, flush=True)
    with mock.patch.dict(os.environ, ENV), contextlib.redirect_stderr(io.StringIO()):
        return asyncio.run(go())


if __name__ == "__main__":
    sys.exit(main())
