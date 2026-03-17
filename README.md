# Artwork Capture Project

Este projeto captura áudio de um microfone em um Raspberry Pi rodando Moode, realiza fingerprinting de áudio para identificar a música tocando, busca artwork de álbuns via APIs e exibe em uma tela conectada. É totalmente automático e transparente para o usuário.

## Quick Start (TL;DR)

```bash
# No Raspberry Pi via SSH:
sudo apt-get update && sudo apt-get install -y python3-dev python3-pip python3-venv ffmpeg libportaudio2 portaudio19-dev git
git clone https://github.com/seu-usuario/artwork-capture.git && cd artwork-capture
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
echo 'export ACOUSTID_API_KEY=0cAcPUvHVU' >> ~/.bashrc && source ~/.bashrc
python src/artwork_capture.py
```

(Veja seção "Instalação Passo a Passo" abaixo para detalhes e configuração completa)

## Funcionalidades
- Captura de áudio via microfone USB
- Fingerprinting de música usando AcoustID
- Recuperação de metadados e artwork via API do MusicBrainz
- Exibição de imagem na tela
- Integração com Moode Audio Player (baseado em MPD)
- Gerenciamento automático de display único (para/ reinicia UI do player)

## Requisitos
- Raspberry Pi 4 Model B com 8GB RAM (ou similar)
- Moode Audio Player (versão mais recente)
- Microfone USB
- Tela conectada (HDMI ou similar)
- Python 3.7+
- Chave de API do AcoustID (gratuita, obtenha em acoustid.org)

## Instalação Passo a Passo

### Pré-requisitos de Sistema (no Raspberry Pi)

Antes de instalar as dependências Python, instale as bibliotecas de sistema necessárias:

```bash
sudo apt-get update
sudo apt-get install -y \
  python3-dev \
  python3-pip \
  python3-venv \
  ffmpeg \
  libportaudio2 \
  portaudio19-dev \
  git
```

**O que cada pacote faz:**
- `python3-dev`: Necessário para compilar PyAudio
- `ffmpeg`: Necessário para fingerprinting de áudio (pyacoustid)
- `portaudio19-dev`: Necessário para PyAudio
- `git`: Para clonar o repositório

### Instalação do Projeto

1. **Clone o repositório no seu Raspberry Pi:**
   ```bash
   git clone https://github.com/seu-usuario/artwork-capture.git
   cd artwork-capture
   ```

2. **Crie e ative um ambiente virtual:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Instale as dependências Python:**
   ```bash
   pip install -r requirements.txt
   ```
   *(Este passo pode levar alguns minutos, especialmente PyAudio)*

4. **Configure a chave da API do AcoustID:**
   - Obtenha uma chave gratuita em [acoustid.org](https://acoustid.org/).
   - Defina a variável de ambiente:
     ```bash
     export ACOUSTID_API_KEY=sua_chave_aqui
     ```
   - Para persistir entre reinicializações, adicione ao seu `~/.bashrc`:
     ```bash
     echo 'export ACOUSTID_API_KEY=sua_chave_aqui' >> ~/.bashrc
     source ~/.bashrc
     ```

5. **Configure permissões para gerenciamento de display (opcional, se tiver tela):**
   - Para controlar a UI do Moode automaticamente, configure sudo sem senha para systemctl:
     ```bash
     sudo visudo
     ```
   - Adicione esta linha no final:
     ```
     pi ALL=(ALL) NOPASSWD: /bin/systemctl stop lighttpd, /bin/systemctl start lighttpd
     ```
   - (Substitua `pi` pelo seu usuário se for diferente)

6. **Teste o setup (opcional):**
   ```bash
   source venv/bin/activate
   python -m pytest tests/test_main.py -v
   ```
   Se todos os testes passarem, o setup está correto.

## Configuração

Edite `src/artwork_capture.py` para ajustar:
- `MIC_DEVICE_INDEX`: Índice do dispositivo de microfone (use `python3 -c "import pyaudio; p = pyaudio.PyAudio(); [print(f'{i}: {p.get_device_info_by_index(i)[\"name\"]}') for i in range(p.get_device_count())]"` para listar dispositivos).
- `DISPLAY_WIDTH` e `DISPLAY_HEIGHT`: Resolução da tela.
- `STOP_UI_CMD` e `START_UI_CMD`: Comandos para parar/iniciar a UI do Moode.
  - Padrão: `["sudo", "systemctl", "stop", "lighttpd"]` e `["sudo", "systemctl", "start", "lighttpd"]`
- `RECORD_SECONDS`: Duração da gravação (10 segundos por padrão).
- `RATE`, `CHUNK`, etc.: Ajustes de áudio se necessário.

## Uso

1. Conecte o microfone USB e a tela ao Pi.
2. Certifique-se de que o Moode está rodando e MPD ativo na porta 6600.
3. Rode o script em background:
   ```
   source venv/bin/activate
   nohup python src/artwork_capture.py &
   ```

### Modo Display (com tela)
O script monitora automaticamente:
- Se MPD estiver tocando (streaming), pula o processamento.
- Se não estiver (fonte analógica), grava áudio, verifica se há som, faz fingerprinting, busca artwork e exibe por 30 segundos.
- Para tela única, para a UI do player temporariamente e reinicia depois.

### Modo Headless (sem tela)
Se nenhuma tela for detectada, o script entra automaticamente em **modo headless**:
- Continua capturando áudio do microfone
- Registra músicas detectadas em `artwork_capture.log` com timestamp, fonte e metadados
- Log rotacionado automaticamente (máx 1MB com backup de 5 arquivos)
- Útil para testar em Pi sem display, ou guardar histórico de músicas tocadas

O arquivo de log é salvo no diretório do projeto e contém:
```
2026-03-17 10:30:45,123 - INFO - DETECTED | Source: vinyl/CD | Artist: The Beatles | Title: Abbey Road
```

## Testes

### Testes Unitários
Para executar os testes unitários (mocks, sem hardware):
```
source venv/bin/activate
python -m pytest tests/test_main.py -v
```

### Testes de Integração (com Microfone e APIs)
Antes de levar para o Pi, teste localmente com seu microfone USB conectado:
```
export ACOUSTID_API_KEY=sua_chave_aqui
source venv/bin/activate
python -m pytest tests/test_integration.py -v
```

Estes testes verificam:
- **Microfone USB**: Listagem de dispositivos, gravação de áudio
- **Conectividade**: AcoustID, MusicBrainz, Cover Art Archive
- **APIs**: Lookup de fingerprints, recuperação de artwork
- **Ciclo Completo**: Gravação → Fingerprinting → Lookup de Metadados (opcional, use música real)

**Dica**: Execute `tests/test_integration.py::TestMicrophoneIntegration::test_microphone_accessible` primeiro para identificar o índice correto do seu microfone USB.

## Troubleshooting

### Problema: Erro ao instalar PyAudio (Raspberry Pi)
Se receber erro durante `pip install -r requirements.txt`:
```
error: Microsoft Visual C++ 14.0 or greater is required
```
Certifique-se de que instalou os pré-requisitos de sistema:
```bash
sudo apt-get install -y python3-dev portaudio19-dev
```
Depois repita: `pip install -r requirements.txt`

### Problema: "Error fingerprinting audio"
Se o log mostrar:
```
ERROR - Error fingerprinting audio: Error
```
FFmpeg não está instalado. Instale-o:
```bash
sudo apt-get install -y ffmpeg
```
Teste:
```bash
which ffmpeg
ffmpeg -version
```

### Problema: Script não encontra microfone
- Verifique dispositivos conectados: `arecord -l` (mostra lista de dispositivos de áudio)
- Liste com PyAudio: `python3 -c "import pyaudio; p = pyaudio.PyAudio(); [print(f'{i}: {p.get_device_info_by_index(i)[\"name\"]}') for i in range(p.get_device_count())]"`
- Ajuste `MIC_DEVICE_INDEX` no `src/artwork_capture.py` com o número correto.

### Problema: Erro de conexão com MPD
- Certifique-se de que Moode está rodando: `ps aux | grep mpd`
- Teste conexão: `echo "status" | nc localhost 6600`
- Reinicie MPD: `sudo systemctl restart mpd`

### Problema: Display não funciona ou conflita
- Para tela única: confirme que `STOP_UI_CMD` e `START_UI_CMD` estão corretos.
- Rode com sudo se necessário: `sudo -E python src/artwork_capture.py` (preserva env vars).
- Se pygame falhar, verifique se a tela suporta gráficos (use HDMI com saída gráfica).

### Problema: Artwork não encontrado
- Nem todas as músicas têm artwork no MusicBrainz.
- Verifique logs para erros de API.

### Problema: Script consome muita CPU/memória
- Reduza `RECORD_SECONDS` ou aumente intervalo de checagem (30s por padrão).
- Rode em background com `nice`.

### Problema: Não roda em boot

#### Opção 1 — Crontab (rápido)
1. Abra o crontab do usuário (geralmente `pi` no Raspbian/Moode):
   ```bash
   crontab -e
   ```
2. Adicione esta linha (ajuste o caminho para o seu projeto):
   ```bash
   @reboot cd /path/to/project && source venv/bin/activate && nohup python src/artwork_capture.py &
   ```

#### Opção 2 — Serviço systemd (recomendado)
1. Crie um arquivo de serviço como `/etc/systemd/system/artwork-capture.service` (use sudo):
   ```ini
   [Unit]
   Description=Artwork Capture
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=/path/to/project
   Environment=ACOUSTID_API_KEY=your_acoustid_api_key
   ExecStart=/path/to/project/venv/bin/python /path/to/project/src/artwork_capture.py
   Restart=on-failure
   User=pi

   [Install]
   WantedBy=multi-user.target
   ```
2. Habilite e inicie o serviço:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable artwork-capture.service
   sudo systemctl start artwork-capture.service
   ```
3. Verifique o status/logs:
   ```bash
   sudo systemctl status artwork-capture.service
   sudo journalctl -u artwork-capture.service -f
   ```

### Logs
- Logs são salvos no console. Para arquivo: `python src/artwork_capture.py > log.txt 2>&1 &`
- Nível de log: INFO por padrão; mude para DEBUG em `logging.basicConfig(level=logging.DEBUG)`.

Se problemas persistirem, verifique os logs e poste no repositório com detalhes do erro.

Adjust `MIC_DEVICE_INDEX`, `DISPLAY_WIDTH`, `DISPLAY_HEIGHT`, and audio threshold in the code as needed.