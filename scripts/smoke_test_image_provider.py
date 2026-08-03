"""Run one credential-safe image Provider smoke test without printing secrets."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv
from PIL import Image

from comicforge_ai.models import build_default_image_registry
from comicforge_ai.models.image_base import ImageModelError
from comicforge_ai.schemas import ImageGenerationRequest, PanelSpec

MODEL_ENVIRONMENTS = {
    "openai-compatible-image": "OPENAI_IMAGE_MODEL",
    "recraft": "RECRAFT_MODEL",
    "together": "TOGETHER_MODEL",
    "siliconflow": "SILICONFLOW_MODEL",
    "fal": "FAL_MODEL",
    "comfyui": "COMFYUI_MODEL",
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    load_dotenv(override=False)
    environment = dict(os.environ)
    model_environment = MODEL_ENVIRONMENTS.get(args.provider)
    if model_environment:
        environment[model_environment] = args.model
    registry = build_default_image_registry(environment)
    try:
        provider = registry.get(args.provider)
    except KeyError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    status = provider.validate_config()
    if not status.configured:
        print(f"配置错误：{status.message}", file=sys.stderr)
        return 2

    output = args.output or Path("outputs") / "provider_smoke" / (
        datetime.now().astimezone().strftime("%Y%m%d_%H%M%S") + ".png"
    )
    panel = PanelSpec(
        sequence=1,
        scene="smoke test",
        visual_description=args.prompt,
        characters=[],
        action="",
        dialogue="",
        narration="",
        image_prompt=args.prompt,
    )
    request = ImageGenerationRequest(
        prompt=args.prompt,
        width=args.width,
        height=args.height,
        seed=args.seed,
        model=args.model,
        panel=panel,
    )
    try:
        result = provider.generate(request, output)
    except ImageModelError as exc:
        safe = provider.redact_secrets(str(exc))
        print(f"生成失败：{type(exc).__name__}：{safe}", file=sys.stderr)
        return 1
    with Image.open(output) as generated:
        dimensions = f"{generated.width}x{generated.height}"
    print(f"Provider: {result.provider_name or result.provider}")
    print(f"模型: {result.model}")
    print(f"请求耗时: {result.duration:.2f} 秒")
    print(f"request_id: {result.request_id or '未返回'}")
    print(f"图片路径: {output.resolve()}")
    print(f"图片尺寸: {dimensions}")
    print("是否发生回退: 否（smoke test 默认严格模式）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
