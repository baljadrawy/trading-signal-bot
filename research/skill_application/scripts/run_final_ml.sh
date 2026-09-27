#!/bin/bash
# تنسيق نهائي: ينتظر التنزيل → يعيد بناء البيانات على الكون الكامل → يشغّل ML النهائي + ضوابط shuffle
set -e
cd /home/tradmin/trading-signal-bot
PY=research/skill_application/.venv/bin/python
OUT=research/skill_application/out
DONE=research/skill_application/data/dl_history.done

echo "[$(date +%H:%M)] waiting for download to finish..."
until [ -f "$DONE" ]; do sleep 20; done
echo "[$(date +%H:%M)] download done: $(cat $DONE)"
echo "symbol dirs: $(ls -d research/skill_application/data/bt_data/*/ | wc -l)"

echo "[$(date +%H:%M)] rebuilding ML dataset on full universe..."
$PY research/skill_application/scripts/ml_dataset.py > $OUT/ml_dataset_build_full.log 2>&1
tail -8 $OUT/ml_dataset_build_full.log

for run in "4h 1.5" "4h 1.5 shuffle" "1d 1.5" "1d 1.5 shuffle" "4h 2.0" "1d 2.0"; do
  echo "[$(date +%H:%M)] ML walk-forward: $run"
  $PY research/skill_application/scripts/ml_walkforward.py $run > "$OUT/run_$(echo $run | tr ' ' '_').log" 2>&1 || echo "  (run failed: $run)"
done

echo "[$(date +%H:%M)] ALL DONE"
date > research/skill_application/data/final_ml.done
