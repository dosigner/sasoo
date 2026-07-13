#!/usr/bin/env python3
"""Sasoo 앱 아이콘 재가공 스크립트.

build/icon.png (원본 616x690 비정사각 RGBA)를 1024x1024 정사각 캔버스로
재배치하고, 그로부터 build/icon.ico(Windows)와 build/icon.icns(macOS,
darwin에서만)를 생성한다.

재실행 가능(멱등): build/icon.png가 이미 1024x1024면 리사이즈 단계는
건너뛰고 ico/icns만 다시 만든다.

요구사항: Pillow (pip install Pillow). macOS의 icns 생성은 시스템 sips /
iconutil CLI를 사용한다(둘 다 macOS 표준 제공 도구).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = REPO_ROOT / "build"
ICON_PNG = BUILD_DIR / "icon.png"
ICON_ICO = BUILD_DIR / "icon.ico"
ICON_ICNS = BUILD_DIR / "icon.icns"

TARGET_SIZE = 1024
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]

# (iconset 파일명, 픽셀 크기)
ICNS_ICONSET_SPECS = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def log(msg: str) -> None:
    print(f"[generate-icons] {msg}")


def ensure_square_1024(src_path: Path) -> Image.Image:
    """src_path의 이미지를 열어 1024x1024 정사각 RGBA로 정규화한다.

    이미 1024x1024면 그대로 반환(리사이즈 스킵), 아니면 LANCZOS로
    1024 박스 안에 비율 유지 스케일 후 투명 캔버스 중앙에 배치한다.
    """
    with Image.open(src_path) as im:
        im = im.convert("RGBA")
        if im.size == (TARGET_SIZE, TARGET_SIZE):
            log(
                f"{src_path.name}는 이미 {TARGET_SIZE}x{TARGET_SIZE} "
                "정사각 — 리사이즈 단계 스킵"
            )
            return im.copy()

        log(f"{src_path.name} 원본 크기 {im.size} 감지 — 리사이즈 진행")
        original_size = im.size
        # Image.thumbnail()은 축소만 지원하고 확대는 하지 않으므로
        # (원본이 1024 박스보다 작은 이 케이스처럼) resize()로 직접
        # 비율 유지 확대/축소 크기를 계산한다.
        scale = min(TARGET_SIZE / im.width, TARGET_SIZE / im.height)
        new_size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
        scaled = im.resize(new_size, Image.LANCZOS)
        log(f"  -> LANCZOS 스케일 결과: {scaled.size}")

        canvas = Image.new("RGBA", (TARGET_SIZE, TARGET_SIZE), (0, 0, 0, 0))
        offset_x = (TARGET_SIZE - scaled.width) // 2
        offset_y = (TARGET_SIZE - scaled.height) // 2
        canvas.paste(scaled, (offset_x, offset_y), scaled)
        log(
            f"  -> {TARGET_SIZE}x{TARGET_SIZE} 투명 캔버스 중앙 배치 "
            f"(offset=({offset_x},{offset_y}), 원본={original_size})"
        )
        return canvas


def write_icon_png(image: Image.Image) -> None:
    if image.size != (TARGET_SIZE, TARGET_SIZE):
        raise ValueError(f"icon.png는 {TARGET_SIZE}x{TARGET_SIZE}이어야 함: {image.size}")
    image.save(ICON_PNG, format="PNG")
    log(f"저장 완료: {ICON_PNG} ({image.size[0]}x{image.size[1]})")


def write_icon_ico(image: Image.Image) -> None:
    image.save(ICON_ICO, format="ICO", sizes=ICO_SIZES)
    log(f"저장 완료: {ICON_ICO} (sizes={ICO_SIZES})")


def write_icon_icns(image: Image.Image) -> None:
    if sys.platform != "darwin":
        log("darwin이 아니므로 icon.icns 생성 스킵")
        return

    iconutil = shutil.which("iconutil")
    if iconutil is None:
        log("경고: iconutil을 찾을 수 없어 icon.icns 생성 스킵")
        return

    with tempfile.TemporaryDirectory(prefix="sasoo-icon-") as tmp:
        iconset_dir = Path(tmp) / "icon.iconset"
        iconset_dir.mkdir()

        for filename, size in ICNS_ICONSET_SPECS:
            resized = image.resize((size, size), Image.LANCZOS)
            resized.save(iconset_dir / filename, format="PNG")

        log(f"iconset 생성 완료: {iconset_dir} ({len(ICNS_ICONSET_SPECS)}개 항목)")

        result = subprocess.run(
            [iconutil, "-c", "icns", str(iconset_dir), "-o", str(ICON_ICNS)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"iconutil 실패 (code={result.returncode}): "
                f"{result.stdout}\n{result.stderr}"
            )
        log(f"저장 완료: {ICON_ICNS}")
    # tempfile.TemporaryDirectory가 with 블록 종료 시 자동 정리


def main() -> int:
    if not ICON_PNG.exists():
        log(f"오류: 소스 파일이 없음: {ICON_PNG}")
        return 1

    normalized = ensure_square_1024(ICON_PNG)
    write_icon_png(normalized)

    # icon.png 저장 이후 디스크에 반영된 최종본을 다시 로드해 ico/icns 생성
    with Image.open(ICON_PNG) as final:
        final = final.convert("RGBA")
        write_icon_ico(final)
        write_icon_icns(final)

    log("모든 아이콘 산출물 생성 완료: icon.png, icon.ico" + (
        ", icon.icns" if sys.platform == "darwin" else " (icns는 darwin 전용, 스킵됨)"
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
