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
# Substitua pela sua chave real ou defina no ambiente
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
            # Tenta um ping para verificar se a conexão ainda está ativa
            if self.mpd_connected:
                try:
                    self.client.ping()
                except ConnectionError:
                    self.mpd_connected = False

            if not self.mpd_connected:
                self.connect_mpd()

            if not self.mpd_connected:
                return True # Se não consegue conectar, assume modo analógico

            status = self.client.status()
            # Se o MPD está tocando algo com título, não escaneamos o analógico
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

        # Tentativa 1: Stereo (seu padrão atual)
        # Tentativa 2: Mono (muitas placas USB PnP só aceitam mono)
        configs = [
            ["-c", "2", "-r", "44100"],
            ["-c", "1", "-r", "44100"],
            ["-c", "1", "-r", "16000"] # Fallback para voz/baixa qualidade
        ]

        for cfg in configs:
            cmd = [
                "arecord",
                "-D", f"hw:{MIC_DEVICE_INDEX},0",
                "-f", "S16_LE",
                *cfg,
                "-d", str(RECORD_SECONDS),
                path
            ]
            
            try:
                logger.info(f"Tentando gravar com {' Stereo' if cfg[1]=='2' else ' Mono'}...")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=RECORD_SECONDS + 5)
                
                if result.returncode == 0:
                    return path
                else:
                    logger.warning(f"Falha na config {cfg}: {result.stderr.strip()}")
            except Exception as e:
                logger.error(f"Erro ao rodar arecord: {e}")

        # Se chegou aqui, todas as tentativas falharam
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
                
                # Conversão segura de buffer para array
                data = np.frombuffer(raw_data, dtype=np.int16).copy()
                
                if len(data) == 0:
                    return False

                if n_channels > 1:
                    data = data.reshape(-1, n_channels)
                    data = data.mean(axis=1).astype(np.int16)

            max_amp = np.max(np.abs(data))
            # Se o som for extremamente baixo, nem processa FFT
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

    # ---------------- ACOUSTID LOOKUP ----------------
    def get_artwork(self, path):
        if not API_KEY or API_KEY == "your_acoustid_api_key":
            logger.error("API Key do AcoustID não configurada.")
            return None

        trimmed = path + "_trim.wav"
        try:
            # Corta os primeiros 5s (pode ser silêncio/agulha descendo)
            subprocess.run(["sox", "-q", path, trimmed, "trim", "5", "15"], check=True)

            # Gera fingerprint e captura a duração exata do arquivo trimado
            cmd = ["fpcalc", "-json", trimmed]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            
            fp_data = json.loads(result.stdout)
            fingerprint = fp_data.get("fingerprint")
            duration = fp_data.get("duration")

            if not fingerprint:
                logger.error("Falha ao gerar fingerprint.")
                return None

            # Consulta AcoustID via POST (necessário para fingerprints longos)
            url = "https://api.acoustid.org/v2/lookup"
            payload = {
                "format": "json",
                "client": API_KEY,
                "fingerprint": fingerprint,
                "duration": int(duration),
                "meta": "recordings releasegroups releases",
            }

            resp = self.session.post(url, data=payload, timeout=15)
            response = resp.json()

            if response.get("status") == "ok" and response.get("results"):
                # Pega o resultado com maior score
                best = max(response["results"], key=lambda x: x.get("score", 0))
                score = best.get("score", 0)
                
                if score > 0.15 and best.get("recordings"):
                    track = best["recordings"][0]
                    title = track.get("title", "Desconhecido")
                    
                    # Tenta obter MBID do Release Group para a capa
                    rgs = track.get("releasegroups", [])
                    if rgs:
                        mbid = rgs[0].get("id")
                        art_url = f"https://coverartarchive.org/release-group/{mbid}/front"
                        img_res = self.session.get(art_url, timeout=10)
                        if img_res.status_code == 200:
                            return {"title": title, "img": img_res.content}
            
            logger.info("Música não identificada ou score baixo.")
            return None

        except Exception as e:
            logger.error(f"Erro AcoustID: {e}")
            return None
        finally:
            if os.path.exists(trimmed):
                os.unlink(trimmed)

    # ---------------- DISPLAY ----------------
    def display_image(self, art_data):
        try:
            if not pygame.display.get_init():
                pygame.display.init()
            
            # Oculta o cursor do mouse (útil em telas touch de 7")
            pygame.mouse.set_visible(False)
            screen = pygame.display.set_mode(DISPLAY_RES)
            
            img_byte = io.BytesIO(art_data["img"])
            img = pygame.image.load(img_byte)
            img = pygame.transform.scale(img, DISPLAY_RES)
            
            screen.blit(img, (0, 0))
            pygame.display.flip()
            
            logger.info(f"Exibindo capa: {art_data['title']}")
            # Mantém a capa por um tempo antes de liberar para o próximo ciclo
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