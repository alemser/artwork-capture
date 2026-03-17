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
import io
from mpd import MPDClient, ConnectionError
from scipy import signal

# --- CONFIGURAÇÕES ---
MIC_DEVICE_INDEX = 3
RECORD_SECONDS = 35 
API_KEY = os.environ.get("ACOUSTID_API_KEY", "your_acoustid_api_key")

DISPLAY_RES = (800, 480)
CHECK_INTERVAL = 5 
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
            if self.mpd_connected:
                try:
                    self.client.ping()
                except ConnectionError:
                    self.mpd_connected = False
            if not self.mpd_connected:
                self.connect_mpd()
            if not self.mpd_connected:
                return True 
            status = self.client.status()
            if status.get("state") == "play":
                song = self.client.currentsong()
                if song and "title" in song:
                    return False
            return True
        except Exception:
            self.mpd_connected = False
            return True

    def record_audio(self):
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="moode_rec_")
        os.close(fd) 

        configs = [
            ["-c", "1", "-r", "48000"],
            ["-c", "1", "-r", "44100"]
        ]

        for cfg in configs:
            cmd = ["arecord", "-D", f"hw:{MIC_DEVICE_INDEX},0", "-f", "S16_LE", *cfg, "-d", str(RECORD_SECONDS), path]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=RECORD_SECONDS + 5)
                if result.returncode == 0:
                    return path
            except Exception:
                continue

        if os.path.exists(path): os.unlink(path)
        return None

    def is_music(self, path):
        try:
            with wave.open(path, "rb") as wf:
                params = wf.getparams()
                data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).copy()
                if len(data) == 0: return False
                if params.nchannels > 1:
                    data = data.reshape(-1, params.nchannels).mean(axis=1).astype(np.int16)

            max_amp = np.max(np.abs(data))
            if max_amp < 500: return False

            freqs, psd = signal.welch(data, fs=params.framerate)
            music_ratio = np.sum(psd > (np.max(psd) * 0.01)) / len(psd)
            logger.info(f"DSP Check: Amp={max_amp} | Ratio={music_ratio:.4f}")
            return music_ratio > THRESHOLD_RATIO
        except Exception as e:
            logger.error(f"Erro DSP: {e}")
            return False

    def get_artwork(self, path):
        if not API_KEY or API_KEY == "your_acoustid_api_key":
            logger.error("API Key ausente.")
            return None
            
        trimmed = path + "_trim.wav"
        debug_path = os.path.join(os.path.expanduser("~"), "test_ident.wav")
        
        try:
            logger.info("Gerando fingerprint de alta precisão...")
            # Deixamos o áudio mais natural (highpass menor e lowpass maior)
            # Isso mantém as características que o AcoustID usa
            subprocess.run([
                "sox", "-q", path, trimmed, 
                "remix", "1", 
                "rate", "16k", 
                "highpass", "100", 
                "lowpass", "7500", 
                "norm", "-1", 
                "trim", "2", "20" # Pulamos só 2s e pegamos 20s de música
            ], check=True)

            subprocess.run(["cp", trimmed, debug_path])

            # Usamos o fpcalc com a opção -length para garantir uma assinatura longa
            cmd = ["fpcalc", "-json", "-length", "20", trimmed]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            fp_data = json.loads(result.stdout)
            
            url = "https://api.acoustid.org/v2/lookup"
            payload = {
                "format": "json",
                "client": API_KEY,
                "fingerprint": fp_data.get("fingerprint"),
                "duration": int(fp_data.get("duration")),
                "meta": "recordings releasegroups releases tracks compress", # Adicionado compress e tracks
                "fuzzy": 1 
            }

            resp = self.session.post(url, data=payload, timeout=15)
            response = resp.json()
            
            logger.info(f"AcoustID Resposta completa: {response.get('status')}")

            if response.get("status") == "ok" and response.get("results"):
                # Se houver QUALQUER resultado, vamos tentar exibir
                results = response.get("results")
                best = max(results, key=lambda x: x.get("score", 0))
                
                # Mesmo com score muito baixo, vamos tentar, pois o áudio está bom
                if best.get("score", 0) > 0.02: 
                    track = best["recordings"][0]
                    title = track.get("title", "Desconhecido")
                    logger.info(f"🎯 SUCESSO: {title} (Score: {best.get('score'):.2f})")

                    rgs = track.get("releasegroups", [])
                    if rgs:
                        mbid = rgs[0].get("id")
                        art_url = f"https://coverartarchive.org/release-group/{mbid}/front"
                        img_res = self.session.get(art_url, timeout=10)
                        if img_res.status_code == 200:
                            return {"title": title, "img": img_res.content}
            
            logger.info("AcoustID: Áudio bom, mas sem match no banco de dados.")
            return None
        except Exception as e:
            logger.error(f"Erro no Lookup: {e}")
            return None
        finally:
            if os.path.exists(trimmed): os.unlink(trimmed)

    def display_image(self, art_data):
        try:
            if not pygame.display.get_init(): pygame.display.init()
            pygame.mouse.set_visible(False)
            screen = pygame.display.set_mode(DISPLAY_RES)
            img = pygame.image.load(io.BytesIO(art_data["img"]))
            screen.blit(pygame.transform.scale(img, DISPLAY_RES), (0, 0))
            pygame.display.flip()
            logger.info(f"Display: Exibindo capa de {art_data['title']}")
            time.sleep(25) 
        except Exception as e:
            logger.error(f"Erro Display: {e}")
        finally:
            pygame.display.quit()

    def start(self):
        logger.info("Monitor Moode Iniciado.")
        while True:
            try:
                if self.should_scan_analog():
                    path = self.record_audio()
                    if path:
                        if self.is_music(path):
                            art = self.get_artwork(path)
                            if art:
                                self.display_image(art)
                        if os.path.exists(path): os.unlink(path)
                time.sleep(CHECK_INTERVAL)
            except KeyboardInterrupt: break
            except Exception as e:
                logger.error(f"Erro Loop: {e}")
                time.sleep(5)

if __name__ == "__main__":
    monitor = MoodeAudioMonitor()
    monitor.start()