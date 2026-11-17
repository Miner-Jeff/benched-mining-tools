#!/bin/sh
# Runs every test with the Python that has GDAL, numpy and scipy installed.
PY=${PYTHON:-python3}
cd "$(dirname "$0")"
for f in test_core.py test_roads.py test_roads2.py test_roads_int.py test_spiral.py test_validate.py test_nodem.py test_buildorder.py test_4326.py smoke.py; do
  echo "== $f"; $PY "$f" 2>&1 | grep -E "FAIL|Traceback|PASSED|SMOKE|PASS$" | tail -3
done
