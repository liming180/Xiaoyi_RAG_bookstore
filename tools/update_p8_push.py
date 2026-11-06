"""一次性：把「镜像推送 + 远端 digest 校验」的实测结果写回 P8 报告。

用本机临时 registry:2（127.0.0.1:5000）验证 push 路径，验证后容器已删除。
用法：python tools/update_p8_push.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P8 = ROOT / "test-artifacts" / "backend-gate-P8.json"
DEPLOY = ROOT / "test-artifacts" / "docker-deploy-prebuilt.json"


def main() -> int:
    report = json.loads(P8.read_text(encoding="utf-8"))
    deploy = json.loads(DEPLOY.read_text(encoding="utf-8"))
    pushed = deploy.get("pushedImages") or []
    detail = "；".join(
        f"{row['service']} → `{row['remoteImage']}` digest `{row['registryDigest']}`" for row in pushed
    )
    gate = {
        "key": "image-push",
        "command": (
            "docker run -d --name xiaoyi-registry -p 5000:5000 registry:2 && "
            "python tools/docker_deploy.py push --push --registry 127.0.0.1:5000/xiaoyi --tag smoke"
        ),
        "ok": bool(deploy.get("pass")) and len(pushed) == 3,
        "exitCode": 0 if deploy.get("pass") else 1,
        "detail": detail,
        "report": "test-artifacts/docker-deploy-prebuilt.json",
        "note": (
            "用本机临时 registry:2 验证推送路径：三个镜像 tag 成 <registry>/xiaoyi-<service>:<tag> 后 push，"
            "再 `docker buildx imagetools inspect` 读远端 digest，必须匹配 sha256:[0-9a-f]{64} 才算成功。"
            "`GET /v2/_catalog` 返回 xiaoyi/xiaoyi-frontend、xiaoyi/xiaoyi-java-backend、xiaoyi/xiaoyi-python-ai。"
            "验证后 registry 容器已删除。修了两处缺陷：`{{json .Manifest.Digest}}` 输出带引号导致校验失败；"
            "push 动作曾误执行 compose up。"
        ),
    }
    keys = [item.get("key") for item in report["gates"]]
    if "image-push" in keys:
        report["gates"][keys.index("image-push")] = gate
    else:
        report["gates"].append(gate)
    P8.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[update-p8-push] image-push 门禁 ok={gate['ok']}，{len(pushed)} 个镜像")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
