cd ~/subika/SWE-agent
source .venv/bin/activate

BASE="/home/deccan-ai-spark-02/subika/swe-bench-taskgen/output/javascript_42tasks_sweagent.jsonl"

for t in 4 5; do
  sweagent run-batch \
    --config config/default.yaml \
    --config config/opus47.yaml \
    --instances.type file \
    --instances.path "$BASE" \
    --instances.deployment.platform linux/amd64 \
    --suffix "_trial_${t}" \
    --redo_existing false \
    --num_workers 8
done