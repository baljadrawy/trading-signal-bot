#!/bin/bash
# G1 isolation re-check of the running collector container (read-only probes; our own container only).
C=tsb-p2-forward-collector
docker inspect $C --format 'id={{slice .Id 0 12}} image={{.Image}} state={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{end}} restart={{.HostConfig.RestartPolicy.Name}} readonly={{.HostConfig.ReadonlyRootfs}} user={{.Config.User}} nanocpus={{.HostConfig.NanoCpus}} mem={{.HostConfig.Memory}} memswap={{.HostConfig.MemorySwap}} pids={{.HostConfig.PidsLimit}} capdrop={{.HostConfig.CapDrop}} capadd={{.HostConfig.CapAdd}} secopt={{.HostConfig.SecurityOpt}} log={{.HostConfig.LogConfig.Type}}{{.HostConfig.LogConfig.Config}} privileged={{.HostConfig.Privileged}} tmpfs={{.HostConfig.Tmpfs}}'
echo "networks: $(docker inspect $C --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}')"
echo "ports: $(docker inspect $C --format '{{json .HostConfig.PortBindings}}') published: $(docker port $C | wc -l)"
echo "mounts:"; docker inspect $C --format '{{range .Mounts}}  {{.Type}} {{.Source}} -> {{.Destination}} rw={{.RW}}{{"\n"}}{{end}}'
echo "env names: $(docker inspect $C --format '{{range .Config.Env}}{{.}}{{"\n"}}{{end}}' | cut -d= -f1 | sort | tr '\n' ' ')"
echo "provenance env (non-secret): $(docker inspect $C --format '{{range .Config.Env}}{{.}}{{"\n"}}{{end}}' | /usr/bin/grep -E '^P2F_(GIT_COMMIT|IMAGE_TAG|BUILD_TIME|IMAGE_ID|CONFIG)=' | tr '\n' ' ')"
echo "docker.sock mounted: $(docker inspect $C --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' | /usr/bin/grep -c docker.sock)"
PGIP=$(docker inspect postgres --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | awk '{print $1}')
GW=$(docker network inspect tsb-p2-forward-net --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}')
echo "## network isolation probes from inside the collector (postgres ip=$PGIP, net gateway=$GW)"
docker exec -i $C python - "$PGIP" "$GW" <<'PY'
import socket, sys
pg, gw = sys.argv[1], sys.argv[2]
for n in ("postgres", "trading_signal_engine", "trading_tracker", "trading_telegram", "trading_scanner", "shared-postgres"):
    try:
        socket.getaddrinfo(n, 5432); print(n, "RESOLVABLE <-- FAIL")
    except OSError:
        print(n, "unresolvable OK")
def probe(h, p):
    s = socket.socket(); s.settimeout(3)
    try:
        s.connect((h, p)); return "OPEN"
    except Exception as e:
        return "closed/unreachable " + type(e).__name__
    finally:
        s.close()
print("postgres", pg, 5432, probe(pg, 5432))
for p in (5432, 6379, 8000, 8080, 3000, 9090, 22, 80, 443):
    print("gateway", gw, p, probe(gw, p))
PY
docker exec $C sh -c 'id; touch /app/x 2>&1 | head -1; ls /var/run/docker.sock 2>&1 | head -1; cat /proc/1/status | /usr/bin/grep -E "^Cap(Eff|Prm|Bnd)" 2>/dev/null || grep -E "^Cap(Eff|Prm|Bnd)" /proc/1/status'
echo "health file: $(docker exec $C cat /data/health/collector_health.json)"
