import os
import time
import logging
import subprocess
import tempfile
import requests
import numpy as np
import wave
import pygame
import json
from mpd import MPDClient, ConnectionError
from scipy import signal

# --- CONFIGURACOES ---
MIC_DEVICE_INDEX = 3
RECORD_SECONDS = 25
API_KEY = os.environ.get("ACOUSTID_API_KEY", "your_acoustid_api_key")

DISPLAY_RES = (800, 480)
CHECK_INTERVAL = 10
THRESHOLD_RATIO = 0.02

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)


class MoodeAudioMonitor:

    def __init__(self):
        self.client = MPDClient()
        self.session = requests.Session()
        self.mpd_connected = False

    # ---------------- MPD ----------------
    def connect_mpd(self):
        try:
            self.client.timeout = 5
            self.client.connect("localhost", 6600)
            self.mpd_connected = True
            logger.info("Conectado ao MPD.")
        except Exception:
            self.mpd_connected = False

    def should_scan_analog(self):
        try:
            if not self.mpd_connected:
                self.connect_mpd()

            status = self.client.status()

            if status.get("state") == "play":
                song = self.client.currentsong()
                if song and "title" in song:
                    return False
            return True
        except (ConnectionError, Exception):
            self.mpd_connected = False
            return True

    # ---------------- AUDIO CAPTURE ----------------
    def record_audio(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name

        cmd = [
            "arecord",
            "-D", f"hw:{MIC_DEVICE_INDEX},0",
            "-f", "S16_LE",
            "-c", "2",             # grava stereo
            "-r", "44100",         # sample rate ideal
            "-d", str(RECORD_SECONDS),
            path
        ]

        try:
            subprocess.run(cmd, capture_output=True, timeout=RECORD_SECONDS + 5)
            logger.info(f"Áudio gravado: {path}")
            return path
        except Exception as e:
            logger.error(f"Erro no arecord: {e}")
            return None

    # ---------------- DSP DETECTION ----------------
    def is_music(self, path):
        try:
            with wave.open(path, "rb") as wf:
                n_channels = wf.getnchannels()
                framerate = wf.getframerate()
                data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                if n_channels > 1:
                    data = data.reshape(-1, n_channels)
                    data = data.mean(axis=1).astype(np.int16)

            max_amp = np.max(np.abs(data))
            freqs, psd = signal.welch(data, fs=framerate)
            music_ratio = np.sum(psd > (np.max(psd) * 0.01)) / len(psd)

            logger.info(f"Sinal: Amp={max_amp} | Ratio={music_ratio:.4f}")
            return music_ratio > THRESHOLD_RATIO
        except Exception as e:
            logger.error(f"Erro DSP: {e}")
            return False

    # ---------------- ACOUSTID LOOKUP ----------------
    def get_artwork(self, path):
        if not API_KEY or API_KEY == "your_acoustid_api_key":
            return None

        try:
            # Trim inicial de 5s para evitar silêncio
            trimmed = path + "_trim.wav"
            subprocess.run(["sox", path, trimmed, "trim", "5"])
            path = trimmed

            # Gerar fingerprint
            cmd = ["fpcalc", "-json", path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                logger.error("Erro executando fpcalc.")
                return None

            data = json.loads(result.stdout)
            fingerprint = data.get("fingerprint")
            if not fingerprint:
                logger.error("Fingerprint não gerado.")
                return None
            logger.info("Fingerprint gerado.")

            # Consulta AcoustID
            url = "https://api.acoustid.org/v2/lookup"
            payload = {
                "format": "json",
                "client": API_KEY,
                "fingerprint": fingerprint,
                "duration": RECORD_SECONDS,
                "meta": "recordings releasegroups releases tracks",
                "fuzzy": 1
            }

            logger.info(json.dumps(payload)[:200])
            resp = self.session.get(url, params=payload, timeout=10)
            logger.info(resp.text[:500])
            response = resp.json()

            if response.get("status") == "ok" and not response.get("results"):
                logger.warning("Servidor recebeu o sinal, mas score baixo.")

            if response.get("status") == "ok" and response.get("results"):
                best = max(response["results"], key=lambda x: x.get("score", 0))
                score = best.get("score", 0)
                logger.info(f"Melhor score: {score:.2f}")

                if score > 0.2 and best.get("recordings"):
                    track = best["recordings"][0]
                    artist = track.get("artists", [{}])[0].get("name", "Desconhecido")
                    title = track.get("title", "Desconhecido")
                    logger.info(f"IDENTIFICADO: {artist} - {title} (Score: {int(score*100)}%)")

                    rgs = track.get("releasegroups", [])
                    if rgs:
                        mbid = rgs[0].get("id")
                        art_url = f"https://coverartarchive.org/release-group/{mbid}/front"
                        img_res = self.session.get(art_url, timeout=5)
                        if img_res.status_code == 200:
                            return {"title": title, "img": img_res.content}

            return None
        except Exception as e:
            logger.error(f"Erro AcoustID: {e}")
            return None

    # ---------------- DISPLAY ----------------
    def display_image(self, art_data):
        try:
            if not pygame.display.get_init():
                pygame.display.init()
            screen = pygame.display.set_mode(DISPLAY_RES)
            import io
            img = pygame.image.load(io.BytesIO(art_data["img"]))
            img = pygame.transform.scale(img, DISPLAY_RES)
            screen.blit(img, (0, 0))
            pygame.display.flip()
            logger.info(f"Exibindo: {art_data['title']}")
            time.sleep(25)
        except Exception as e:
            logger.error(f"Erro display: {e}")
        finally:
            pygame.display.quit()

    # ---------------- MAIN LOOP ----------------
    def start(self):
        logger.info("Monitor Analógico Iniciado.")
        while True:
            if self.should_scan_analog():
                path = self.record_audio()
                if path:
                    if self.is_music(path):
                        art = self.get_artwork(path)
                        if art:
                            self.display_image(art)
                    os.unlink(path)
            time.sleep(CHECK_INTERVAL)


# ---------------- MAIN ----------------
if __name__ == "__main__":
    monitor = MoodeAudioMonitor()
    monitor.start()