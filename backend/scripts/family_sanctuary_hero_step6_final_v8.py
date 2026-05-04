#!/usr/bin/env python3
"""Family Sanctuary hero — Step 6 final composition (v8).

Muxes chopped v7 video + R2 narration + Azure character TTS + music bed + title.

Run inside ``nate_backend`` (needs ffmpeg, AZURE_* env, R2_* env):

  docker cp backend/scripts/family_sanctuary_hero_step6_final_v8.py \\
    nate_backend:/tmp/family_sanctuary_hero_step6_final_v8.py

  docker exec -w /app nate_backend env PYTHONPATH=/app \\
    python3 /tmp/family_sanctuary_hero_step6_final_v8.py

Place base MP4 first:

  docker cp ... nate_backend:/tmp/family_sanctuary_v7_chop_keep10_crossfade.mp4

Optional env:
  FS_V8_BASE_MP4 — default /tmp/family_sanctuary_v7_chop_keep10_crossfade.mp4
  FS_V8_MUSIC_R2_KEY — optional WAV/MP3 on R2; else lavfi strings drone
  FS_SKIP_VOICE_UPLOAD — set to 1 to skip uploading generated voices to R2
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

BASE_DEFAULT = "/tmp/family_sanctuary_v7_chop_keep10_crossfade.mp4"
OUT_LOCAL = "/tmp/family_sanctuary_hero_FINAL_v8.mp4"
NARR_PREFIX = "sse/trailer/family_sanctuary/narration"
VOICE_PREFIX = "sse/trailer/family_sanctuary/voices"
FINAL_R2_KEY = "sse/trailer/family_sanctuary/final/hero_FINAL_v8.mp4"
BUCKET = os.environ.get("R2_DEFAULT_BUCKET", "nate-vault").strip()

# R2 ships 3 segments: Acts 1+2 combined, Act 3, Act 4.
# Character stingers are anchored after segments 1, 2, 3 respectively.
NARRATION_KEYS = (
    f"{NARR_PREFIX}/segment_1_acts_1_2.wav",
    f"{NARR_PREFIX}/segment_2_act_3.wav",
    f"{NARR_PREFIX}/segment_3_act_4.wav",
)

CHARACTER_LINES: tuple[tuple[str, str, float, str], ...] = (
    ("daughter.wav", "Mama, I was seen and heard!", 1.0, "nova"),
    ("father.wav", "The family first!", 0.95, "onyx"),
    ("son.wav", "I have the courage!", 1.0, "alloy"),
    ("mother.wav", "We made it. Together.", 0.9, "shimmer"),
)

NATE_LEAD_S = 0.5
NATE_GAP_S = 0.4
CHAR_PAD_S = 0.3
MUSIC_TAIL_S = 1.5


def _run(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)


def _ffprobe_duration(path: str) -> float:
    r = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        timeout=30,
    )
    try:
        return float((r.stdout or "").strip())
    except ValueError:
        return 0.0


def _s3_client():
    import boto3
    from botocore.config import Config

    account = os.environ.get("R2_ACCOUNT_ID", "").strip()
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    if not endpoint and account:
        endpoint = f"https://{account}.r2.cloudflarestorage.com"
    if not endpoint:
        raise RuntimeError("Set R2_ACCOUNT_ID (endpoint derived); never rely on missing R2_ENDPOINT_URL.")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "adaptive"}),
        region_name="auto",
    )


def _r2_download(s3, key: str, dest: str) -> None:
    s3.download_file(BUCKET, key, dest)


def _r2_upload(s3, local: str, key: str, content_type: str) -> None:
    s3.upload_file(local, BUCKET, key, ExtraArgs={"ContentType": content_type})


def _normalize_peak_dbfs(inp: str, outp: str, target_dbfs: float = -3.0) -> None:
    r = _run(["ffmpeg", "-i", inp, "-af", "volumedetect", "-f", "null", "-"], timeout=60)
    err = r.stderr or ""
    m = re.search(r"max_volume:\s*([-\d.]+)\s*dB", err)
    if not m:
        shutil.copyfile(inp, outp)
        return
    peak_db = float(m.group(1))
    gain_db = target_dbfs - peak_db
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            inp,
            "-af",
            f"volume={gain_db:.4f}dB",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-sample_fmt",
            "s16",
            outp,
        ],
        check=True,
        timeout=120,
    )


def _wav_to_stereo_normalized_for_delay(path: str, out: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            path,
            "-af",
            "pan=stereo|c0=c0|c1=c0",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-sample_fmt",
            "s16",
            out,
        ],
        check=True,
        timeout=120,
    )


async def _tts_line(text: str, voice: str, speed: float, out_wav: str) -> None:
    from app.sse.trailer_generator import _azure_tts

    audio = await _azure_tts(
        text=text,
        voice=voice,
        instructions="Speak clearly with warm emotional presence. One short line only.",
        response_format="wav",
        speed=float(speed),
    )
    if not audio:
        raise RuntimeError(f"Azure TTS failed for voice={voice!r}")
    raw = out_wav + ".raw.wav"
    with open(raw, "wb") as f:
        f.write(audio)
    _normalize_peak_dbfs(raw, out_wav)
    try:
        os.remove(raw)
    except OSError:
        pass


def _find_dejavu_bold() -> str:
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    ):
        if os.path.isfile(p):
            return p
    return "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"


def _escape_drawtext_fontpath(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:")


def _build_music_bed_raw(s3, work: str, duration: float) -> str:
    """Write ``music_bed_raw.wav`` (~−14 dBFS bed) length ``duration`` seconds."""
    music_path = os.path.join(work, "music_source.wav")
    raw_out = os.path.join(work, "music_bed_raw.wav")
    key = os.environ.get("FS_V8_MUSIC_R2_KEY", "").strip()
    if key:
        try:
            _r2_download(s3, key, music_path)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    music_path,
                    "-t",
                    str(duration),
                    "-af",
                    "highpass=f=80,lowpass=f=4200,volume=-14dB",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-sample_fmt",
                    "s16",
                    raw_out,
                ],
                check=True,
                timeout=300,
            )
            return raw_out
        except Exception as exc:
            print("[FS-V8] R2 music failed, using drone:", exc)

    dur = max(duration, 1.0)
    expr = "0.04*sin(2*PI*196*t)+0.028*sin(2*PI*293*t)+0.018*sin(2*PI*392*t)"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc={expr}:s=44100:d={dur:.3f}",
            "-af",
            "lowpass=f=2200,highpass=f=120,afade=t=in:st=0:d=2,volume=-14dB",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-sample_fmt",
            "s16",
            raw_out,
        ],
        check=True,
        timeout=300,
    )
    return raw_out


def _apply_music_envelope(
    inp: str,
    outp: str,
    duration: float,
    mother_e: float,
    *,
    music_tail_s: float,
) -> None:
    """Swell toward ~−10 dBFS (mid bed) and tail from mother end to ~−28 dBFS."""
    ga = 10 ** (4 / 20)
    gb = 10 ** (-14 / 20)
    me = mother_e
    ts = music_tail_s
    me_ts = me + ts
    # Commas escaped for filtergraph; hold post-tail at gb
    vol = (
        f"volume=if(lt(t\\,5.25)\\,1\\,"
        f"if(lt(t\\,8.25)\\,1+({ga}-1)*(t-5.25)/3\\,"
        f"if(lt(t\\,{me:.6f})\\,{ga}\\,"
        f"if(lt(t\\,{me_ts:.6f})\\,{ga}+({gb}-{ga})*((t-{me:.6f})/{ts:.6f})\\,{gb}))))"
        f":eval=frame"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            inp,
            "-af",
            vol,
            "-t",
            str(duration),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-sample_fmt",
            "s16",
            outp,
        ],
        check=True,
        timeout=300,
    )


def main() -> None:
    base_mp4 = os.environ.get("FS_V8_BASE_MP4", BASE_DEFAULT).strip()
    if not os.path.isfile(base_mp4):
        raise SystemExit(f"Missing base video: {base_mp4}")

    base_dur = _ffprobe_duration(base_mp4)
    print("[FS-V8] Base video duration", base_dur)

    work = tempfile.mkdtemp(prefix="fs_v8_")
    try:
        s3 = _s3_client()

        # ── Character voices ─────────────────────────────────────────────
        async def gen_voices() -> None:
            for fname, text, spd, voice in CHARACTER_LINES:
                await _tts_line(text, voice, spd, os.path.join(work, fname))

        asyncio.run(gen_voices())

        narr_paths = []
        for i, key in enumerate(NARRATION_KEYS):
            lp = os.path.join(work, f"narr_act{i + 1}.wav")
            _r2_download(s3, key, lp)
            narr_paths.append(lp)

        # Durations
        n_durs = [_ffprobe_duration(p) for p in narr_paths]
        c_durs = {
            fname: _ffprobe_duration(os.path.join(work, fname))
            for fname, _, _, _ in CHARACTER_LINES
        }
        print("[FS-V8] Narration durations", [round(x, 3) for x in n_durs])
        print("[FS-V8] Character durations", {k: round(v, 3) for k, v in c_durs.items()})

        # Timeline (acts sequential; character stingers per brief)
        t = NATE_LEAD_S
        a_starts: list[float] = []
        a_ends: list[float] = []
        for i, d in enumerate(n_durs):
            a_starts.append(t)
            t += d
            a_ends.append(t)
            if i < len(n_durs) - 1:
                t += NATE_GAP_S

        d_daughter = c_durs["daughter.wav"]
        d_father = c_durs["father.wav"]
        d_son = c_durs["son.wav"]
        d_mother = c_durs["mother.wav"]

        # 3-segment narration (acts 1+2, act 3, act 4); stingers after each.
        daughter_s = a_ends[0] + CHAR_PAD_S
        father_s = a_ends[1] + CHAR_PAD_S
        son_s = father_s + d_father + 0.2
        mother_s = a_ends[2] + CHAR_PAD_S

        daughter_e = daughter_s + d_daughter
        father_e = father_s + d_father
        son_e = son_s + d_son
        mother_e = mother_s + d_mother

        timeline_end = mother_e + MUSIC_TAIL_S

        estimate_plain = (
            sum(n_durs)
            + sum(c_durs.values())
            + max(0, len(n_durs) - 1) * NATE_GAP_S
            + 3 * CHAR_PAD_S
        )
        print("[FS-V8] Rough checklist sum (acts+chars+gaps)", round(estimate_plain, 3))
        print("[FS-V8] Timeline end (mother + music tail)", round(timeline_end, 3))

        # Narration-driven duration; cap raised to 30s after asset-length review.
        if timeline_end > 30.0:
            raise SystemExit(
                f"ABORT: timeline_end={timeline_end:.2f}s > 30s — shorten narration assets or adjust gaps."
            )

        if not (22.0 <= timeline_end <= 25.5):
            print(
                "[FS-V8] WARN: duration outside 22–25.5s target — proceeding (narration-driven).",
            )

        if os.environ.get("FS_SKIP_VOICE_UPLOAD", "").strip() != "1":
            for fname, _, _, _ in CHARACTER_LINES:
                _r2_upload(
                    s3,
                    os.path.join(work, fname),
                    f"{VOICE_PREFIX}/{fname}",
                    "audio/wav",
                )
                print("[FS-V8] Uploaded voice", fname)

        # Prepare delayed stereo stems
        stems: list[tuple[str, float]] = [
            (narr_paths[i], a_starts[i]) for i in range(len(narr_paths))
        ] + [
            (os.path.join(work, "daughter.wav"), daughter_s),
            (os.path.join(work, "father.wav"), father_s),
            (os.path.join(work, "son.wav"), son_s),
            (os.path.join(work, "mother.wav"), mother_s),
        ]
        delayed: list[str] = []
        for i, (src, start) in enumerate(stems):
            stereo = os.path.join(work, f"st_{i}.wav")
            delayed_f = os.path.join(work, f"dl_{i}.wav")
            _wav_to_stereo_normalized_for_delay(src, stereo)
            ms = max(0, int(round(start * 1000)))
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    stereo,
                    "-af",
                    f"adelay={ms}|{ms}",
                    delayed_f,
                ],
                check=True,
                timeout=120,
            )
            delayed.append(delayed_f)

        # Voice bus
        mix_ins: list[str] = []
        for p in delayed:
            mix_ins.extend(["-i", p])
        n_in = len(delayed)
        voice_bus = os.path.join(work, "voice_bus.wav")
        fc_v = "".join(f"[{i}:a]" for i in range(n_in)) + f"amix=inputs={n_in}:normalize=0:duration=longest[vox]"
        subprocess.run(
            ["ffmpeg", "-y", *mix_ins, "-filter_complex", fc_v, "-map", "[vox]", voice_bus],
            check=True,
            timeout=300,
        )

        # Music + sidechain duck
        music_raw = _build_music_bed_raw(s3, work, timeline_end + 1.0)
        music_bed = os.path.join(work, "music_bed.wav")
        _apply_music_envelope(
            music_raw,
            music_bed,
            timeline_end + 0.25,
            mother_e,
            music_tail_s=MUSIC_TAIL_S,
        )
        ducked_mix = os.path.join(work, "audio_ducked.wav")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                music_bed,
                "-i",
                voice_bus,
                "-filter_complex",
                "[1:a]asplit[voice][sc];"
                "[0:a][sc]sidechaincompress=threshold=0.08:ratio=3:attack=30:release=350:mix=0.8[m1];"
                "[m1][voice]amix=inputs=2:duration=longest:dropout_transition=2[mout]",
                "-map",
                "[mout]",
                "-t",
                str(timeline_end),
                "-ar",
                "44100",
                "-ac",
                "2",
                "-sample_fmt",
                "s16",
                ducked_mix,
            ],
            check=True,
            timeout=600,
        )

        # Video: freeze extend
        extend = max(0.0, timeline_end - base_dur)
        last_png = os.path.join(work, "last_frame.png")
        freeze_mp4 = os.path.join(work, "freeze_ext.mp4")
        ext_base = os.path.join(work, "extended_base.mp4")

        seek_ss = max(0.0, base_dur - 0.08)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{seek_ss:.3f}",
                "-i",
                base_mp4,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                last_png,
            ],
            check=True,
            timeout=120,
        )
        if not os.path.isfile(last_png) or os.path.getsize(last_png) == 0:
            # Fallback: re-encode-then-seek
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    base_mp4,
                    "-vf",
                    f"select='eq(n\\,{int(base_dur * 24) - 1})'",
                    "-frames:v",
                    "1",
                    last_png,
                ],
                check=True,
                timeout=180,
            )

        if extend > 0.01:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    last_png,
                    "-t",
                    str(extend),
                    "-vf",
                    "scale=848:480,format=yuv420p,fps=24",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    freeze_mp4,
                ],
                check=True,
                timeout=300,
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    base_mp4,
                    "-i",
                    freeze_mp4,
                    "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                    "-map",
                    "[v]",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    ext_base,
                ],
                check=True,
                timeout=600,
            )
        else:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    base_mp4,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    ext_base,
                ],
                check=True,
                timeout=600,
            )

        font = _escape_drawtext_fontpath(_find_dejavu_bold())
        t_intro = max(0.0, mother_e - 0.5)
        t_outro = timeline_end
        fade_out_start = max(mother_e, t_outro - 1.0)

        alpha_expr = (
            f"if(lt(t\\,{t_intro:.4f})\\,0\\,"
            f"if(lt(t\\,{mother_e:.4f})\\,(t-{t_intro:.4f})/0.5\\,"
            f"if(lt(t\\,{fade_out_start:.4f})\\,1\\,"
            f"if(lt(t\\,{t_outro:.4f})\\,(1-(t-{fade_out_start:.4f})/1.0)\\,0))))"
        )

        vf = (
            f"drawtext=fontfile={font}:text='FAMILY SANCTUARY':fontsize=36:fontcolor=#E8C77A:"
            f"x=(w-text_w)/2:y=h-130:shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha={alpha_expr},"
            f"drawtext=fontfile={font}:text='by Sovereign Sanctuary':fontsize=18:fontcolor=#E8C77A:"
            f"x=(w-text_w)/2:y=h-92:shadowcolor=black@0.6:shadowx=2:shadowy=2:alpha={alpha_expr}"
        )

        video_titled = os.path.join(work, "video_title.mp4")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                ext_base,
                "-vf",
                vf,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "24",
                video_titled,
            ],
            check=True,
            timeout=600,
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_titled,
                "-i",
                ducked_mix,
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                str(timeline_end),
                "-movflags",
                "+faststart",
                OUT_LOCAL,
            ],
            check=True,
            timeout=600,
        )

        out_dur = _ffprobe_duration(OUT_LOCAL)
        print("[FS-V8] FINAL duration", round(out_dur, 3), "(target was", round(timeline_end, 3), ")")
        if abs(out_dur - timeline_end) > 0.15:
            print("[FS-V8] WARN: duration drift vs timeline >0.15s")

        # Verify streams
        pr = _run(
            ["ffprobe", "-v", "error", "-show_streams", "-print_format", "json", OUT_LOCAL],
            timeout=30,
        )
        meta = json.loads(pr.stdout or "{}")
        streams = meta.get("streams") or []
        print(
            "[FS-V8] streams:",
            [(s.get("codec_type"), s.get("codec_name"), s.get("width"), s.get("sample_rate")) for s in streams],
        )
        vnames = [s.get("codec_name") for s in streams if s.get("codec_type") == "video"]
        anames = [s.get("codec_name") for s in streams if s.get("codec_type") == "audio"]
        if vnames != ["h264"] or len(anames) != 1 or anames[0] not in ("aac", "aac_latm"):
            print("[FS-V8] WARN: expected 1×h264 video + 1×aac audio, got", vnames, anames)

        _r2_upload(s3, OUT_LOCAL, FINAL_R2_KEY, "video/mp4")
        print("[FS-V8] Uploaded", FINAL_R2_KEY)
        print("[FS-V8] Done local:", OUT_LOCAL)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
