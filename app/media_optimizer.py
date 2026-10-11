"""Video optimalisatie module voor Halloween Projection Control.

Inspecteert en optimaliseert videobestanden in media/background en media/effects:
1. FastStart: verplaatst de moov atom naar het begin van de MP4 (0% CPU, <0.5s) zodat de beamer direct start zonder bufferen.
2. Codec-conversie: converteert niet-ondersteunde codecs (zoals AV1) automatisch naar H.264 + AAC.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("halloween.optimizer")

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}


def is_faststart_mp4(file_path: Path) -> bool:
    """Controleert of de moov atom vooraan in het MP4-bestand staat."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(4096)
            moov_pos = header.find(b"moov")
            mdat_pos = header.find(b"mdat")
            if moov_pos != -1:
                if mdat_pos == -1 or moov_pos < mdat_pos:
                    return True
        return False
    except Exception as e:
        logger.warning("Kon faststart niet controleren voor %s: %s", file_path, e)
        return False


def inspect_video_stream(file_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Haalt video- en audiocodec op via ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=codec_type,codec_name",
            "-of", "json",
            str(file_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            vcodec = None
            acodec = None
            for s in data.get("streams", []):
                ctype = s.get("codec_type")
                cname = s.get("codec_name")
                if ctype == "video" and not vcodec:
                    vcodec = cname
                elif ctype == "audio" and not acodec:
                    acodec = cname
            return vcodec, acodec
    except Exception as e:
        logger.warning("ffprobe mislukt voor %s: %s", file_path, e)
    return None, None


class MediaOptimizer:
    def __init__(self, media_dir: Path):
        self.media_dir = media_dir
        self.is_running = False
        self.current_file = ""
        self.processed_count = 0
        self.total_count = 0
        self.last_status: Dict[str, Any] = {}

    def get_health_report(self) -> Dict[str, Any]:
        """Scant alle videobestanden en geeft een rapport terug."""
        background_dir = self.media_dir / "background"
        effects_dir = self.media_dir / "effects"

        files_to_check: List[Path] = []
        for d in [background_dir, effects_dir]:
            if d.is_dir():
                for f in sorted(d.iterdir()):
                    if (
                        f.is_file()
                        and f.suffix.lower() in VIDEO_EXTENSIONS
                        and not f.name.endswith(".tmp.mp4")
                        and not f.name.endswith(".part")
                        and f.stat().st_size > 0
                    ):
                        files_to_check.append(f)

        report_files = []
        needs_optimization_count = 0

        for f in files_to_check:
            faststart = is_faststart_mp4(f) if f.suffix.lower() == ".mp4" else False
            vcodec, acodec = inspect_video_stream(f)

            # Heuristiek: h264 en aac/mp3 met faststart is optimaal
            is_h264 = vcodec == "h264" if vcodec else True
            needs_transcode = bool(vcodec and vcodec not in ("h264",))
            needs_faststart = (not faststart) and (not needs_transcode)
            is_optimal = faststart and not needs_transcode

            if not is_optimal:
                needs_optimization_count += 1

            report_files.append({
                "path": str(f.relative_to(self.media_dir)),
                "name": f.name,
                "video_codec": vcodec or "onbekend",
                "audio_codec": acodec or "geen/onbekend",
                "faststart": faststart,
                "needs_transcode": needs_transcode,
                "needs_faststart": needs_faststart,
                "is_optimal": is_optimal,
            })

        return {
            "is_running": self.is_running,
            "current_file": self.current_file,
            "total_videos": len(files_to_check),
            "optimal_count": len(files_to_check) - needs_optimization_count,
            "needs_optimization": needs_optimization_count,
            "files": report_files,
        }

    async def optimize_all(
        self, progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> Dict[str, Any]:
        """Optimaliseert alle bestanden die dat nodig hebben."""
        if self.is_running:
            return {"success": False, "message": "Optimalisatie is al bezig."}

        self.is_running = True
        self.processed_count = 0
        self.current_file = ""

        try:
            health = self.get_health_report()
            candidates = [f for f in health["files"] if not f["is_optimal"]]
            self.total_count = len(candidates)

            if not candidates:
                self.is_running = False
                return {"success": True, "message": "Alle bestanden zijn al geoptimaliseerd.", "optimized": 0}

            optimized_success = 0
            for item in candidates:
                rel_path = item["path"]
                full_path = self.media_dir / rel_path
                if not full_path.exists():
                    continue

                self.current_file = full_path.name
                if progress_callback:
                    await progress_callback({
                        "is_running": True,
                        "current_file": self.current_file,
                        "processed": self.processed_count,
                        "total": self.total_count,
                    })

                tmp_target = full_path.with_name(f"{full_path.stem}.tmp.mp4")

                try:
                    if item["needs_transcode"]:
                        # Volledige transcode naar H.264 + AAC + FastStart
                        logger.info("Transcoderen van %s naar H.264...", full_path.name)
                        cmd = [
                            "ffmpeg", "-y",
                            "-i", str(full_path),
                            "-c:v", "libx264",
                            "-preset", "fast",
                            "-crf", "22",
                            "-c:a", "aac",
                            "-b:a", "192k",
                            "-movflags", "+faststart",
                            str(tmp_target),
                        ]
                    else:
                        # Alleen FastStart fix (stream copy, 0% CPU)
                        logger.info("Toepassen van FastStart op %s...", full_path.name)
                        cmd = [
                            "ffmpeg", "-y",
                            "-i", str(full_path),
                            "-c", "copy",
                            "-movflags", "+faststart",
                            str(tmp_target),
                        ]

                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()

                    if proc.returncode == 0 and tmp_target.exists() and tmp_target.stat().st_size > 0:
                        # Vervang origineel atomair
                        shutil.move(str(tmp_target), str(full_path))
                        optimized_success += 1
                        logger.info("Succesvol geoptimaliseerd: %s", full_path.name)
                    else:
                        logger.error("FFmpeg fout bij %s: %s", full_path.name, stderr.decode("utf-8", errors="ignore"))
                        if tmp_target.exists():
                            tmp_target.unlink()
                except Exception as ex:
                    logger.exception("Fout tijdens optimaliseren van %s: %s", full_path.name, ex)
                    if tmp_target.exists():
                        tmp_target.unlink()

                self.processed_count += 1
                if progress_callback:
                    await progress_callback({
                        "is_running": True,
                        "current_file": self.current_file,
                        "processed": self.processed_count,
                        "total": self.total_count,
                    })

            return {
                "success": True,
                "message": f"{optimized_success} van de {self.total_count} bestanden geoptimaliseerd.",
                "optimized": optimized_success,
            }
        finally:
            self.is_running = False
            self.current_file = ""
            if progress_callback:
                await progress_callback({
                    "is_running": False,
                    "current_file": "",
                    "processed": self.processed_count,
                    "total": self.total_count,
                })
