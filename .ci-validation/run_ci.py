"""在隔离测试环境直接执行候选 CI 的 run 步骤，不复制维护另一套命令。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

import yaml

parser = argparse.ArgumentParser()
parser.add_argument("job", choices=["quality", "web", "package", "rust-linux", "windows-smoke"])
parser.add_argument("--evidence", required=True, type=Path)
parser.add_argument("--from-step", type=int, default=0)
args = parser.parse_args()
root = Path.cwd()
workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
args.evidence.mkdir(parents=True, exist_ok=True)
results = []
for index, step in enumerate(workflow["jobs"][args.job]["steps"]):
    if "run" not in step or index < args.from_step:
        continue
    name = step.get("name", str(index))
    env = os.environ.copy()
    if "npm_config_prefix" in env:
        env["PATH"] = str(Path(env["npm_config_prefix"]) / "bin") + os.pathsep + env.get("PATH", "")
    for key, value in step.get("env", {}).items():
        value = str(value).replace("${{ github.workspace }}", str(root))
        if "${{" in value:
            raise RuntimeError(f"尚未处理的 GitHub 表达式：{key}")
        if key == "CCCC_LAUNCHER_PATH" and "CARGO_TARGET_DIR" in env:
            value = str(Path(env["CARGO_TARGET_DIR"]) / "debug/cccc")
        env[key] = value
    log = args.evidence / f"{args.job}-{index:02d}.log"
    print(f"开始 {args.job}: {name}", flush=True)
    started = time.time()
    command = (["pwsh", "-NoProfile", "-Command", "$ErrorActionPreference='Stop'; " + step["run"] + "; if ($LASTEXITCODE) { exit $LASTEXITCODE }"]
               if os.name == "nt" else ["bash", "-e", "-o", "pipefail", "-c", step["run"]])
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(command, env=env, stdout=output, stderr=subprocess.STDOUT, check=False,
                                timeout=step["timeout-minutes"] * 60 if "timeout-minutes" in step else None)
    results.append({"step": name, "exit_code": result.returncode, "seconds": round(time.time()-started, 2), "log": str(log)})
    (args.evidence / f"{args.job}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结束 {name}: {result.returncode} ({results[-1]['seconds']} 秒)", flush=True)
    if result.returncode:
        print(log.read_text(encoding="utf-8", errors="replace")[-12000:], flush=True)
        raise SystemExit(result.returncode)
