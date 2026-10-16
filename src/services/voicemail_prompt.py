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
    try:
        os.makedirs(PROMPTS_DIR, exist_ok=True)
        os.makedirs("/var/lib/freeswitch/recordings/voicemail", exist_ok=True)
    except OSError:
        pass
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


IVR_WELCOME_FALLBACK = "/var/lib/freeswitch/recordings/prompts/ivr_welcome.wav"


def ensure_ivr_prompt() -> str:
    """
    Ensures a default IVR welcome prompt audio file exists:
    'Thank you for calling. Please dial your party's extension, or press a menu option, or wait on the line.'

    Returns the absolute path to the 8kHz mono WAV audio file, or a tone_stream fallback.
    """
    try:
        os.makedirs(PROMPTS_DIR, exist_ok=True)
    except OSError:
        pass

    target_wav = IVR_WELCOME_FALLBACK
    if os.path.exists(target_wav) and os.path.getsize(target_wav) > 1000:
        return target_wav

    phrase = "Thank you for calling. Please dial your party's extension, or press a menu option, or wait on the line to be connected."

    # Method 1: Google TTS via httpx + ffmpeg conversion to 8000Hz mono WAV
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
                logger.info(f"Successfully generated dynamic IVR welcome prompt: {target_wav}")
                return target_wav
    except Exception as e:
        logger.warning(f"Google TTS generation failed for IVR welcome prompt: {e}")

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
            logger.info("Successfully generated IVR welcome prompt via gTTS")
            return target_wav
    except Exception as e:
        logger.warning(f"gTTS library generation failed for IVR welcome prompt: {e}")

    # Method 3: Check FreeSWITCH Callie system sounds
    for callie_path in (
        "/usr/share/freeswitch/sounds/en/us/callie/ivr/8000/ivr-welcome.wav",
        "/usr/share/freeswitch/sounds/en/us/callie/ivr/8000/ivr-welcome_to_freeswitch.wav",
        "/usr/share/freeswitch/sounds/en/us/callie/ivr/8000/ivr-enter_ext_number.wav"
    ):
        if os.path.exists(callie_path) and os.path.getsize(callie_path) > 1000:
            return callie_path

    # Method 4: Return tone_stream if no sound file can be generated
    return "tone_stream://%(2000,4000,440,480)"


CONF_PIN_FALLBACK = "/var/lib/freeswitch/recordings/prompts/conf_pin.wav"
CONF_BAD_PIN_FALLBACK = "/var/lib/freeswitch/recordings/prompts/conf_bad_pin.wav"


def ensure_conference_pin_prompt() -> str:
    """
    Ensures a conference PIN prompt audio file exists:
    'Please enter your conference PIN number, followed by pound.'
    Returns absolute path or Callie system path.
    """
    try:
        os.makedirs(PROMPTS_DIR, exist_ok=True)
    except OSError:
        pass

    target_wav = CONF_PIN_FALLBACK
    if os.path.exists(target_wav) and os.path.getsize(target_wav) > 1000:
        return target_wav

    # Check Callie system sounds first
    for callie_path in (
        "/usr/share/freeswitch/sounds/en/us/callie/conference/8000/conf-pin.wav",
        "/usr/share/freeswitch/sounds/en/us/callie/conference/conf-pin.wav"
    ):
        if os.path.exists(callie_path) and os.path.getsize(callie_path) > 1000:
            return callie_path

    phrase = "Please enter your conference PIN number, followed by pound."

    # Method 1: Google TTS
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
            proc.communicate(input=r.content)
            if proc.returncode == 0 and os.path.exists(target_wav) and os.path.getsize(target_wav) > 1000:
                logger.info(f"Successfully generated dynamic conference PIN prompt: {target_wav}")
                return target_wav
    except Exception as e:
        logger.warning(f"Google TTS generation failed for conf PIN prompt: {e}")

    # Fallback to relative Callie path or tone stream
    return "conference/conf-pin.wav"


def ensure_conference_bad_pin_prompt() -> str:
    """
    Ensures a conference bad PIN prompt audio file exists:
    'That PIN is invalid. Goodbye.'
    Returns absolute path or Callie system path.
    """
    try:
        os.makedirs(PROMPTS_DIR, exist_ok=True)
    except OSError:
        pass

    target_wav = CONF_BAD_PIN_FALLBACK
    if os.path.exists(target_wav) and os.path.getsize(target_wav) > 1000:
        return target_wav

    # Check Callie system sounds first
    for callie_path in (
        "/usr/share/freeswitch/sounds/en/us/callie/conference/8000/conf-bad-pin.wav",
        "/usr/share/freeswitch/sounds/en/us/callie/conference/conf-bad-pin.wav"
    ):
        if os.path.exists(callie_path) and os.path.getsize(callie_path) > 1000:
            return callie_path

    phrase = "That PIN is invalid. Goodbye."

    # Method 1: Google TTS
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
            proc.communicate(input=r.content)
            if proc.returncode == 0 and os.path.exists(target_wav) and os.path.getsize(target_wav) > 1000:
                logger.info(f"Successfully generated dynamic conference bad PIN prompt: {target_wav}")
                return target_wav
    except Exception as e:
        logger.warning(f"Google TTS generation failed for conf bad PIN prompt: {e}")

    return "conference/conf-bad-pin.wav"

