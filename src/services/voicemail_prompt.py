import os
import logging
import subprocess
import httpx

logger = logging.getLogger("pbx.voicemail_prompt")

PROMPTS_DIR = "/var/lib/freeswitch/recordings/prompts"
DEFAULT_FALLBACK = "/var/lib/freeswitch/recordings/prompts/voicemail_greeting.wav"


def ensure_voicemail_prompt(ext_num: str) -> str:
    """
    Ensures a customized voicemail audio greeting exists for the given extension:
    'User at extension {extension number} is not available, please leave a voice message after the beep'

    Returns the absolute path to the 8kHz mono WAV audio file for FreeSWITCH playback.
    """
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    target_wav = os.path.join(PROMPTS_DIR, f"voicemail_{ext_num}.wav")

    # If the customized prompt already exists and is non-empty, use it
    if os.path.exists(target_wav) and os.path.getsize(target_wav) > 1000:
        return target_wav

    # Synthesize the audio
    spoken_ext = " ".join(list(ext_num.strip()))
    phrase = f"User at extension {spoken_ext} is not available, please leave a voice message after the beep."

    # Method 1: Google TTS API via httpx + ffmpeg conversion to 8000Hz mono WAV
    try:
        url = "https://translate.google.com/translate_tts"
        params = {"ie": "UTF-8", "q": phrase, "tl": "en", "client": "tw-ob"}
        headers = {"User-Agent": "Mozilla/5.0"}
        r = httpx.get(url, params=params, headers=headers, timeout=5.0)
        if r.status_code == 200 and len(r.content) > 500:
            proc = subprocess.Popen(
                ["ffmpeg", "-y", "-i", "pipe:0", "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", target_wav],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = proc.communicate(input=r.content)
            if proc.returncode == 0 and os.path.exists(target_wav) and os.path.getsize(target_wav) > 1000:
                logger.info(f"Successfully generated dynamic voicemail prompt for extension {ext_num}: {target_wav}")
                return target_wav
    except Exception as e:
        logger.warning(f"Google TTS generation failed for extension {ext_num}: {e}")

    # Method 2: gTTS library if installed
    try:
        from gtts import gTTS
        import tempfile
        tts = gTTS(text=phrase, lang="en", tld="com")
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
            temp_mp3 = tf.name
        tts.save(temp_mp3)
        subprocess.run(
            ["ffmpeg", "-y", "-i", temp_mp3, "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", target_wav],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if os.path.exists(temp_mp3):
            os.remove(temp_mp3)
        if os.path.exists(target_wav) and os.path.getsize(target_wav) > 1000:
            logger.info(f"Successfully generated voicemail prompt via gTTS for extension {ext_num}")
            return target_wav
    except Exception as e:
        logger.warning(f"gTTS library generation failed for extension {ext_num}: {e}")

    # Method 3: Fallback to existing generic greeting if available
    if os.path.exists(DEFAULT_FALLBACK) and os.path.getsize(DEFAULT_FALLBACK) > 1000:
        return DEFAULT_FALLBACK

    return target_wav
