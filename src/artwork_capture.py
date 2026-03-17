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
        except Exception as e:
            logger.error(f"Falha ao conectar ao MPD: {e}")
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
        except Exception as e:
            logger.warning(f"Erro ao checar status MPD: {e}")
            self.mpd_connected = False
            return True

    # ---------------- AUDIO CAPTURE ----------------
    def record_audio(self):
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="moode_rec_")
        os.close(fd) 

        # Tentamos Mono primeiro, que é o que seu hardware USB PnP aceita
        configs = [
            ["-c", "1", "-r", "44100"],
            ["-c", "2", "-r", "44100"]
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

    # ---------------- DSP DETECTION ----------------
    def is_music(self, path):
        try:
            with wave.open(path, "rb") as wf:
                n_channels = wf.getnchannels()
                framerate = wf.getframerate()
                n_frames = wf.getnframes()
                raw_data = wf.readframes(n_frames)
                data = np.frombuffer(raw_data, dtype=np.int16).copy()
                
                if len(data) == 0: return False

                if n_channels > 1:
                    data = data.reshape(-1, n_channels)
                    data = data.mean(axis=1).astype(np.int16)

            max_amp = np.max(np.abs(data))
            if max_amp < 500: 
                logger.info(f"Sinal muito baixo (Amp={max_amp}). Pulando.")
                return False

            freqs, psd = signal.welch(data, fs=framerate)
            max_psd = np.max(psd)
            if max_psd == 0: return False

            music_ratio = np.sum(psd > (max_psd * 0.01)) / len(psd)
            logger.info(f"DSP Check: Amp={max_amp} | Ratio={music_ratio:.4f}")
            
            return music_ratio > THRESHOLD_RATIO

        except Exception as e:
            logger.error(f"Erro DSP detalhado: {e}", exc_info=True)
            return False

    # ---------------- ACOUSTID LOOKUP (Versão Unificada para Microfone) ----------------
    def get_artwork(self, path):
        if not API_KEY or API_KEY == "your_acoustid_api_key":
            logger.error("API Key não configurada.")
            return None

        trimmed = path + "_trim.wav"
        try:
            # AJUSTE PARA MICROFONE (IPHONE):
            # Abrimos o highpass para 150Hz (mais corpo) 
            # Abrimos o lowpass para 10000Hz (mais detalhes/agudos)
            # Isso torna o fingerprint muito mais único para a API
            logger.info("Refinando áudio para identificação aérea...")
            subprocess.run([
                "sox", "-q", path, trimmed, 
                "remix", "1", 
                "highpass", "150", 
                "lowpass", "10000", 
                "norm", "-1", 
                "trim", "3", "17" # Pulamos menos e pegamos um trecho maior (14s)
            ], check=True)

            # --- COPIAR PARA PASTA DE TESTE ---
            # Isso salva o áudio processado em /var/lib/mpd/music/test_ident.wav
            # Você poderá ouvir esse arquivo pelo próprio Moode Audio!
            subprocess.run(["cp", trimmed, "~/test_ident.wav"])
            logger.info("Arquivo de teste salvo em ~/test_ident.wav")

            cmd = ["fpcalc", "-json", trimmed]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            fp_data = json.loads(result.stdout)
            
            fingerprint = fp_data.get("fingerprint")
            duration = fp_data.get("duration")

            if not fingerprint:
                return None

            url = "https://api.acoustid.org/v2/lookup"
            payload = {
                "format": "json",
                "client": API_KEY,
                "fingerprint": fingerprint,
                "duration": int(duration),
                "meta": "recordings releasegroups releases", # Adicionado releases
                "fuzzy": 1 
            }

            resp = self.session.post(url, data=payload, timeout=15)
            response = resp.json()
            
            logger.info(f"Resposta API: {response.get('status')} - Resultados: {len(response.get('results', []))}")

            if response.get("status") == "ok" and response.get("results"):
                # No microfone, aceitamos scores baixos devido à perda acústica
                results = [r for r in response["results"] if r.get("score", 0) > 0.05]
                
                if results:
                    best = max(results, key=lambda x: x.get("score", 0))
                    score_percent = int(best.get("score", 0) * 100)
                    
                    # Tenta pegar o título
                    track = best["recordings"][0]
                    title = track.get("title", "Desconhecido")
                    
                    logger.info(f"🎯 IDENTIFICADO: {title} (Confiança: {score_percent}%)")

                    rgs = track.get("releasegroups", [])
                    if rgs:
                        mbid = rgs[0].get("id")
                        art_url = f"https://coverartarchive.org/release-group/{mbid}/front"
                        img_res = self.session.get(art_url, timeout=10)
                        if img_res.status_code == 200:
                            return {"title": title, "img": img_res.content}
            
            logger.info("AcoustID: Sem correspondência. Tente aproximar o microfone ou trocar a música.")
            return None

        except Exception as e:
            logger.error(f"Erro no AcoustID: {e}")
            return None
        finally:
            if os.path.exists(trimmed):
                os.unlink(trimmed)

    # ---------------- DISPLAY ----------------
    def display_image(self, art_data):
        try:
            if not pygame.display.get_init():
                pygame.display.init()
            
            pygame.mouse.set_visible(False)
            screen = pygame.display.set_mode(DISPLAY_RES)
            
            img_byte = io.BytesIO(art_data["img"])
            img = pygame.image.load(img_byte)
            img = pygame.transform.scale(img, DISPLAY_RES)
            
            screen.blit(img, (0, 0))
            pygame.display.flip()
            
            logger.info(f"Exibindo capa: {art_data['title']}")
            time.sleep(30) 
            
        except Exception as e:
            logger.error(f"Erro display: {e}")
        finally:
            pygame.display.quit()

    # ---------------- MAIN LOOP ----------------
    def start(self):
        logger.info("Monitor Analógico Moode Audio Iniciado.")
        while True:
            try:
                if self.should_scan_analog():
                    path = self.record_audio()
                    if path:
                        if self.is_music(path):
                            art = self.get_artwork(path)
                            if art:
                                self.display_image(art)
                        
                        if os.path.exists(path):
                            os.unlink(path)
                
                time.sleep(CHECK_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")
                time.sleep(CHECK_INTERVAL)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    monitor = MoodeAudioMonitor()
    monitor.start()