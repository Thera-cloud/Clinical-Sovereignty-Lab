#!/bin/bash
export SKYEYE_AUDIT_TOKEN=$(ssh -o ConnectTimeout=10 root@68.183.168.75 "grep '^SKYEYE_AUDIT_TOKEN=' /opt/clinical-sovereignty-lab/.env | tail -n 1 | cut -d= -f2")
python3 "/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/blue_harvester.py" \
  --all \
  --config "/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/blue_harvester_config.yaml" \
  --rate-limit 0 \
  --model qwen2.5-coder:7b \
  --max-chunks 20
