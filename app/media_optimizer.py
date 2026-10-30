"""Video & Audio optimalisatie module voor Halloween Projection Control.

Inspecteert en optimaliseert mediabestanden in media/background, media/effects en media/audio:
1. FastStart: verplaatst de moov atom naar het begin van MP4-video's (0% CPU, <0.5s) zodat de beamer direct start zonder bufferen.
2. Codec-conversie: converteert niet-ondersteunde videocodecs (zoals AV1) automatisch naar H.264 + AAC.
3. Audio-normalisatie: balanceert alle geluidseffecten volgens de EBU R128 (-16 LUFS, True Peak -1.5 dBTP) standaard
   zodat kreten niet oversturen en zachte whispers goed hoorbaar blijven.
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("halloween.optimizer")

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}

TARGET_AUDIO_LUFS = -16.0
TARGET_AUDIO_TP = -1.5


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
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=10)
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


def measure_audio_loudness(file_path: Path) -> Tuple[Optional[float], Optional[float]]:
    """Meet de geïntegreerde luidheid (LUFS) en True Peak (dBFS) via FFmpeg ebur128 filter."""
    try:
        cmd = [
            "ffmpeg",
            "-nostats",
            "-i", str(file_path),
            "-af", "ebur128=peak=true:framelog=quiet",
            "-f", "null",
            "-",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=15)
        m_i = re.search(r"Integrated loudness:\s+I:\s+([-\d.]+)\s+LUFS", res.stderr)
        m_tp = re.search(r"True peak:\s+Peak:\s+([-\d.]+)\s+dBFS", res.stderr)
        val_i = float(m_i.group(1)) if m_i else None
        val_tp = float(m_tp.group(1)) if m_tp else None
        return val_i, val_tp
    except Exception as e:
        logger.warning("ebur128 luidheidsmeting mislukt voor %s: %s", file_path, e)
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
        """Scant alle video- en audiobestanden en geeft een statusrapport terug."""
        background_dir = self.media_dir / "background"
        effects_dir = self.media_dir / "effects"
        audio_dir = self.media_dir / "audio"

        video_files: List[Path] = []
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
                        video_files.append(f)

        audio_files: List[Path] = []
        if audio_dir.is_dir():
            for f in sorted(audio_dir.iterdir()):
                if (
                    f.is_file()
                    and f.suffix.lower() in AUDIO_EXTENSIONS
                    and not f.name.endswith(".tmp.mp3")
                    and not f.name.endswith(".part")
                    and f.stat().st_size > 0
                ):
                    audio_files.append(f)

        report_files = []
        needs_optimization_count = 0

        # Video inspectie
        for f in video_files:
            faststart = is_faststart_mp4(f) if f.suffix.lower() == ".mp4" else False
            vcodec, acodec = inspect_video_stream(f)

            is_h264 = vcodec == "h264" if vcodec else True
            needs_transcode = bool(vcodec and vcodec not in ("h264",))
            needs_faststart = (not faststart) and (not needs_transcode)
            is_optimal = faststart and not needs_transcode

            if not is_optimal:
                needs_optimization_count += 1

            report_files.append({
                "type": "video",
                "path": str(f.relative_to(self.media_dir)),
                "name": f.name,
                "video_codec": vcodec or "onbekend",
                "audio_codec": acodec or "geen/onbekend",
                "faststart": faststart,
                "needs_transcode": needs_transcode,
                "needs_faststart": needs_faststart,
                "is_optimal": is_optimal,
            })

        # Audio inspectie
        for f in audio_files:
            lufs, tp = measure_audio_loudness(f)
            # Een audiobestand is optimaal als het binnen de broadcast-bandbreedte [-24.0, -13.0] LUFS valt
            # én geen digitale clipping vertoont (true peak <= -1.0 dBFS).
            # Dit voorkomt onnodige her-encodering van reeds genormaliseerde korte percussieve effecten
            # (zoals klopgeluiden) met hoge pieken en dynamiek.
            is_optimal = False
            if lufs is not None and tp is not None:
                if -24.0 <= lufs <= -13.0 and tp <= -1.0:
                    is_optimal = True

            if not is_optimal:
                needs_optimization_count += 1

            report_files.append({
                "type": "audio",
                "path": str(f.relative_to(self.media_dir)),
                "name": f.name,
                "loudness_lufs": lufs,
                "true_peak_dbfs": tp,
                "needs_audio_norm": not is_optimal,
                "is_optimal": is_optimal,
            })

        total_media = len(video_files) + len(audio_files)

        return {
            "is_running": self.is_running,
            "current_file": self.current_file,
            "total_videos": len(video_files),
            "total_audios": len(audio_files),
            "total_media": total_media,
            "optimal_count": total_media - needs_optimization_count,
            "needs_optimization": needs_optimization_count,
            "files": report_files,
        }

    async def optimize_all(
        self, progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> Dict[str, Any]:
        """Optimaliseert alle video- en audiobestanden die dat nodig hebben."""
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

                media_type = item.get("type", "video")
                self.current_file = full_path.name
                if progress_callback:
                    await progress_callback({
                        "is_running": True,
                        "current_file": self.current_file,
                        "processed": self.processed_count,
                        "total": self.total_count,
                        "step": "Audio normaliseren..." if media_type == "audio" else "Video optimaliseren...",
                    })

                if media_type == "audio":
                    # Audio EBU R128 normalisatie naar MP3
                    tmp_target = full_path.with_name(f"{full_path.stem}.tmp.mp3")
                    logger.info("Normaliseren van audiobestand %s naar EBU R128 (-16 LUFS)...", full_path.name)
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", str(full_path),
                        "-af", f"loudnorm=I={TARGET_AUDIO_LUFS}:TP={TARGET_AUDIO_TP}:LRA=11",
                        "-c:a", "libmp3lame",
                        "-b:a", "192k",
                        "-vn",
                        str(tmp_target),
                    ]
                else:
                    # Video optimalisatie
                    tmp_target = full_path.with_name(f"{full_path.stem}.tmp.mp4")
                    if item.get("needs_transcode"):
                        # Volledige transcode naar H.264 + AAC + FastStart
                        logger.info("Transcoderen van video %s naar H.264...", full_path.name)
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
                        logger.info("Toepassen van FastStart op video %s...", full_path.name)
                        cmd = [
                            "ffmpeg", "-y",
                            "-i", str(full_path),
                            "-c", "copy",
                            "-movflags", "+faststart",
                            str(tmp_target),
                        ]

                try:
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

