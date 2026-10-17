# Host operational definitions (version-controlled templates)

This directory versions the **non-secret** host-level definitions the running system depends on, outside the trading Compose project:
- the P2 forward collector's Compose project;
- its runtime configuration;
- the collector monitor's systemd user units;
- the TSB jobs in the service account's crontab.

**Nothing here installs, schedules or restarts anything.** Installing or changing any of these on the host is a separate, owner-approved operational action.

## Files and classes

| Template | Installed as | Class |
|---|---|---|
| `p2-forward/compose.yml` | `${TSB_HOME}/ops/tsb-p2-forward/compose.yml` | Versioned as is. It is already parameterized by environment (`P2F_IMAGE`, `P2F_IMAGE_ID`, `P2F_DATA_DIR`, `P2F_CONFIG_FILE`, supplied by `p2f_continuous_up.sh`). It includes the deployed G3 limits (1.5 CPU / 768 MB, see `docs/p2/P2F_G3_RESIZE_READINESS.md` on `ops/g3-stage-g-20261008`). |
| `p2-forward/configs/continuous-v1.json.tmpl` | `${TSB_HOME}/ops/tsb-p2-forward/configs/continuous-v1.json` | Template: `host_label` is host-specific. |
| `systemd/tsb-p2f-monitor.service.tmpl` | `${TSB_HOME}/.config/systemd/user/tsb-p2f-monitor.service` | Template: absolute host paths. |
| `systemd/tsbops.slice` | `${TSB_HOME}/.config/systemd/user/tsbops.slice` | Versioned as is (no host values). |
| `cron/tsb.crontab.tmpl` | 3 lines in `crontab -l` | Template: the canary watchdog, the nightly p1bg backup (installed v1, currently failing; see `ops/tsb-p1bg/README.md`), and the collector daily seal and backup. |

`values/netcup-vps-arm64.env` holds the current host's values. They are paths and a host label only, **never credentials**. `INSTALL_MAP.tsv` maps each template to its installed location.

**Never committed here:**
- `.env*` and any credential;
- the collector monitor binding and history (`monitor/*.binding.json*`) and its outputs;
- `research-data/**`;
- logs;
- the temporary A56 soak-monitor cron line;
- other projects' cron lines (xsch, wishlist, shared-postgres, hermes);
- transient research units (`rj-*`).

## Verify (read-only)

```
python3 ops/host/render.py compare ops/host/values/netcup-vps-arm64.env
```

Result on 2026-10-18 (exit 0):

```
IDENTICAL ops/host/p2-forward/compose.yml ... sha256=06f32bc51974cdfc
IDENTICAL ops/host/p2-forward/configs/continuous-v1.json.tmpl ... sha256=ebe6be133c51a01e
IDENTICAL ops/host/systemd/tsb-p2f-monitor.service.tmpl ... sha256=8861897a7f9e2cb6
IDENTICAL ops/host/systemd/tsbops.slice ... sha256=9cebd793c61f635b
PRESENT   ops/host/cron/tsb.crontab.tmpl: 3 job lines verbatim in crontab -l
```

The live crontab was also byte-identical to the A56.6 record `~/ops/tsb-a56-upgrade-kit/a566/crontab.after.txt` (sha256 `14c1f18918b8c840…`).

## Notes

- The installed unit's `Documentation=` URL points at branch `feature/g4-monitor-supervision-20261007`. It is kept verbatim so the rendered file stays byte-identical.
- The collector host scripts that these definitions call (`p2f_*.py`, `p2f_*.sh`, `verifier/verify_*.py`) are versioned by the collector runtime-import PR under `p2_forward/ops` and `p2_forward/verifier`. The host directory `~/ops/tsb-p2-forward` is a flattened install of those.
