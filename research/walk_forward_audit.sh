#!/usr/bin/env bash
# ============================================================================
# walk_forward_audit.sh — فاحص حافة دوري (out-of-sample) على DB الحيّ
# ----------------------------------------------------------------------------
# الغرض: حارس ضد ادعاءات "الحافة" الزائفة. يقيس التوقّع الصافي بعد الرسوم على
#        نوافذ زمنية مستقلة (walk-forward) ويصدر حُكم PASS/FAIL.
#
# قاعدة القرار (يجب أن تتحقق الثلاثة معاً لإعلان حافة قابلة للتنفيذ):
#   1) PF صافي (بعد الرسوم) > 1.0 على كامل العيّنة
#   2) التوقّع الصافي موجب في >= 2 من آخر 3 أشهر (ثبات عبر النوافذ)
#   3) لا تركيز مفرط: حذف أعلى 5 صفقات لا يقلب الإجمالي من موجب إلى سالب
# أي إخفاق => "لا حافة — أبقِ التجميد". تدقيق 2026-06-23: الوضع الحالي FAIL.
#
# الاستخدام:  bash research/walk_forward_audit.sh            # تقرير للشاشة
#             FEE_PCT=0.3 POS_USDT=50 bash research/...      # تخصيص الرسوم
#             bash research/walk_forward_audit.sh --telegram # إرسال ملخص (إن توفّر)
# يُشغَّل دورياً عبر cron. لا يكتب أي شيء في DB (قراءة فقط).
# ============================================================================
set -euo pipefail

FEE_PCT="${FEE_PCT:-0.3}"          # رسوم ذهاب+إياب % (0.1%/جهة × 2 = 0.2؛ التقرير التاريخي استخدم 0.3)
POS_USDT="${POS_USDT:-50}"         # حجم الصفقة الافتراضي
FEE_USD=$(awk "BEGIN{printf \"%.4f\", ${POS_USDT}*${FEE_PCT}/100}")
PG_CONT="${PG_CONT:-postgres}"
PG_USER="${PG_USER:-trading_signal_bot}"
PG_DB="${PG_DB:-trading_signals}"

Q(){ docker exec -i "$PG_CONT" psql -U "$PG_USER" -d "$PG_DB" -t -A -F'|' -c "$1"; }

echo "================================================================"
echo " WALK-FORWARD EDGE AUDIT — $(date -u '+%Y-%m-%d %H:%M UTC')"
echo " fee_roundtrip=${FEE_PCT}%  pos=\$${POS_USDT}  fee=\$${FEE_USD}/trade"
echo "================================================================"

echo ""
echo "── (1) OVERALL (all closed trades) ───────────────────────────"
Q "SELECT
  'n='||count(*)||'  WR='||round(100.0*sum((result='WIN')::int)/count(*),1)||'%'
  ||'  gross_exp=\$'||round(avg(profit_usdt)::numeric,3)
  ||'  net_exp=\$'||round(avg(profit_usdt-${FEE_USD})::numeric,3)
  ||'  net_sum=\$'||round(sum(profit_usdt-${FEE_USD})::numeric,1)
  ||'  PF_gross='||round((sum(CASE WHEN profit_usdt>0 THEN profit_usdt ELSE 0 END)
        /NULLIF(-sum(CASE WHEN profit_usdt<0 THEN profit_usdt ELSE 0 END),0))::numeric,3)
  ||'  PF_net='||round((sum(CASE WHEN profit_usdt-${FEE_USD}>0 THEN profit_usdt-${FEE_USD} ELSE 0 END)
        /NULLIF(-sum(CASE WHEN profit_usdt-${FEE_USD}<0 THEN profit_usdt-${FEE_USD} ELSE 0 END),0))::numeric,3)
 FROM trade_results;"

echo ""
echo "── (2) MONTHLY WALK-FORWARD (out-of-sample windows) ──────────"
printf "  %-8s %5s %6s %9s %9s %7s\n" month n WR% net_exp net_sum PF_net
Q "SELECT to_char(exit_time,'YYYY-MM'), count(*),
   round(100.0*sum((result='WIN')::int)/count(*),1),
   round(avg(profit_usdt-${FEE_USD})::numeric,3),
   round(sum(profit_usdt-${FEE_USD})::numeric,1),
   round((sum(CASE WHEN profit_usdt-${FEE_USD}>0 THEN profit_usdt-${FEE_USD} ELSE 0 END)
     /NULLIF(-sum(CASE WHEN profit_usdt-${FEE_USD}<0 THEN profit_usdt-${FEE_USD} ELSE 0 END),0))::numeric,3)
 FROM trade_results GROUP BY 1 ORDER BY 1;" \
 | awk -F'|' '{printf "  %-8s %5s %6s %9s %9s %7s\n",$1,$2,$3,$4,$5,$6}'

echo ""
echo "── (3) ROLLING 14-DAY (recent regime) ───────────────────────"
Q "SELECT 'last14d: n='||count(*)||'  WR='||COALESCE(round(100.0*sum((result='WIN')::int)/NULLIF(count(*),0),1)::text,'-')
   ||'%  net_exp=\$'||COALESCE(round(avg(profit_usdt-${FEE_USD})::numeric,3)::text,'-')
   ||'  net_sum=\$'||COALESCE(round(sum(profit_usdt-${FEE_USD})::numeric,1)::text,'0')
 FROM trade_results WHERE exit_time >= NOW()-INTERVAL '14 days';"

echo ""
echo "── (4) GATE COHORTS (stoch / divergence contribution) ────────"
printf "  %-20s %5s %6s %9s %9s\n" cohort n WR% net_exp net_sum
Q "WITH j AS (SELECT t.profit_usdt, t.result,
     COALESCE((s.score_details->>'stoch_rsi')::numeric,0) st,
     COALESCE((s.score_details->>'rsi_divergence')::numeric,0) dv
   FROM trade_results t JOIN signals s ON s.id=t.signal_id)
 SELECT CASE WHEN st>0 AND dv>0 THEN 'COMBO(st&div)'
             WHEN st>0 THEN 'stoch>0_only'
             WHEN dv>0 THEN 'div>0_only'
             ELSE 'both=0' END,
   count(*), round(100.0*sum((result='WIN')::int)/count(*),1),
   round(avg(profit_usdt-${FEE_USD})::numeric,3), round(sum(profit_usdt-${FEE_USD})::numeric,1)
 FROM j GROUP BY 1 ORDER BY 4 DESC;" \
 | awk -F'|' '{printf "  %-20s %5s %6s %9s %9s\n",$1,$2,$3,$4,$5}'

echo "  ↳ COMBO month-distribution (artifact check):"
Q "WITH j AS (SELECT t.exit_time, t.result,
     COALESCE((s.score_details->>'stoch_rsi')::numeric,0) st,
     COALESCE((s.score_details->>'rsi_divergence')::numeric,0) dv
   FROM trade_results t JOIN signals s ON s.id=t.signal_id)
 SELECT '     '||to_char(exit_time,'YYYY-MM')||': n='||count(*)||' wins='||sum((result='WIN')::int)
 FROM j WHERE st>0 AND dv>0 GROUP BY to_char(exit_time,'YYYY-MM') ORDER BY 1;"

echo ""
echo "── (5) CONCENTRATION (drop top-N winners, gross sum) ─────────"
Q "WITH r AS (SELECT profit_usdt, row_number() OVER (ORDER BY profit_usdt DESC) rn FROM trade_results)
 SELECT '  all=\$'||round(sum(profit_usdt)::numeric,1)
   ||'  drop_top5=\$'||round(sum(profit_usdt) FILTER (WHERE rn>5)::numeric,1)
   ||'  drop_top20=\$'||round(sum(profit_usdt) FILTER (WHERE rn>20)::numeric,1) FROM r;"

echo ""
echo "── VERDICT ───────────────────────────────────────────────────"
VERDICT=$(Q "
WITH base AS (SELECT profit_usdt-${FEE_USD} ne, profit_usdt g,
              row_number() OVER (ORDER BY profit_usdt DESC) rn FROM trade_results),
 pf AS (SELECT (sum(CASE WHEN ne>0 THEN ne ELSE 0 END)/NULLIF(-sum(CASE WHEN ne<0 THEN ne ELSE 0 END),0)) pf_net FROM base),
 conc AS (SELECT sum(g) all_g, sum(g) FILTER (WHERE rn>5) drop5_g FROM base),
 mon AS (SELECT to_char(exit_time,'YYYY-MM') m, avg(profit_usdt-${FEE_USD}) ne
         FROM trade_results GROUP BY 1 ORDER BY 1 DESC LIMIT 3),
 monpos AS (SELECT count(*) FILTER (WHERE ne>0) pos FROM mon)
SELECT CASE WHEN (SELECT pf_net FROM pf) > 1.0
              AND (SELECT pos FROM monpos) >= 2
              AND (SELECT drop5_g FROM conc) > 0
            THEN 'PASS — حافة قابلة للتنفيذ (راجع يدوياً قبل أي نشر)'
            ELSE 'FAIL — لا حافة. أبقِ التجميد + paper.' END
  ||'  [PF_net='||round((SELECT pf_net FROM pf)::numeric,3)
  ||', months_pos='||(SELECT pos FROM monpos)||'/3'
  ||', drop5_gross=\$'||round((SELECT drop5_g FROM conc)::numeric,1)||']';")
echo "  $VERDICT"
echo "================================================================"

if [[ "${1:-}" == "--telegram" ]]; then
  ENV_FILE="$(dirname "$0")/../.env"
  TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
  CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)
  if [[ -n "${TOKEN}" && -n "${CHAT}" ]]; then
    MSG="🔍 Walk-Forward Audit $(date -u '+%Y-%m-%d %H:%M')%0A${VERDICT}"
    curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
      -d chat_id="${CHAT}" -d text="${MSG}" >/dev/null && echo "  (telegram sent)"
  else
    echo "  (telegram skipped — no token/chat in .env)"
  fi
fi
