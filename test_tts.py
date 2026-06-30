"""
test_tts.py - try out the ElevenLabs voice (and key rotation) WITHOUT making a whole video.

It loads your config.json (so your ElevenLabs keys / voice are picked up exactly like a real
run), generates a short sample line, KEEPS the mp3 so you can listen, and prints which key was
used so you can confirm rotation/failover. Run it a few times to watch the key rotate.

Usage:
    python test_tts.py                       # default sample line, ElevenLabs only
    python test_tts.py "Your own test line"  # custom text
    python test_tts.py --auto                # full engine chain (EL -> Gemini -> Edge), like a real run

Output: writes tts_sample.mp3 in this folder. Open/play it to hear the voice.
"""
import sys
import os

import tts
import config_loader


def main():
    args = [a for a in sys.argv[1:]]
    engine = "elevenlabs"
    if "--auto" in args:
        engine = "auto"
        args.remove("--auto")
    text = args[0] if args else (
        "You grab a small drink, and it somehow floods the entire cup holder. "
        "There is a hidden reason airports design it exactly this way."
    )

    cfg = config_loader.load_config("config.json")

    # show what keys are visible (masked) so you can confirm the pool is loaded
    tts._TTS_CFG = cfg
    pool = tts._elevenlabs_keys()
    if pool:
        print(f"[test] ElevenLabs key pool loaded: {len(pool)} key(s): "
              + ", ".join("…" + (k[-6:] if len(k) >= 6 else k) for k in pool))
    else:
        print("[test] NO ElevenLabs keys found in config.json or env. "
              "Add them to 'elevenlabs_api_keys' or set HL_ELEVENLABS_API_KEYS.")
        if engine == "elevenlabs":
            print("[test] Nothing to test for ElevenLabs. Exiting.")
            return

    out_mp3 = "tts_sample.mp3"
    out_json = "tts_sample_timings.json"
    print(f"[test] Engine: {engine}")
    print(f"[test] Text: {text!r}")
    print("[test] Generating... (watch for which key/engine is used below)\n")

    try:
        words = tts.synthesize(
            text, out_mp3, out_json,
            api_key=cfg.get("gemini_api_key", ""),
            engine=engine,
            cfg=cfg,
        )
    except Exception as e:
        print(f"[test] FAILED: {e}")
        return

    if words:
        dur = words[-1]["end"] if words else 0
        print(f"\n[test] SUCCESS - {len(words)} words, audio ~{dur:.1f}s")
        print(f"[test] Saved: {os.path.abspath(out_mp3)}")
        print("[test] >>> Open/play tts_sample.mp3 to hear the voice. <<<")
        print("[test] Run this script again to confirm the key rotates to the next one.")
    else:
        print("[test] No audio produced.")


if __name__ == "__main__":
    main()
