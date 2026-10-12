import os
import wave
import json
import audioop
import numpy as np
import speech_recognition as sr
from vosk import Model, KaldiRecognizer, SpkModel, SetLogLevel

# IMPORTAÇÃO DA INTEGRAÇÃO
try:
    from backend.processador_voz.processador_voz import TranscritorVoz
except ImportError:
    # Fallback para caso rode o script fora da estrutura de pacotes
    from processador_voz import TranscritorVoz

# --- CONFIGURAÇÃO DE TESTE ---
MODO_TESTE_SOZINHO = False


class Diarizador:
    """
    Integração: Vosk (Diarização) + TranscritorVoz (Google Speech).
    """

    def __init__(self, model_path, spk_model_path):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Modelo Texto não encontrado: {model_path}")
        if not os.path.exists(spk_model_path):
            raise FileNotFoundError(f"Modelo Falante não encontrado: {spk_model_path}")

        SetLogLevel(-1)  # Logs limpos

        print("[AUDIO_SERVICE] Carregando modelos IA (Logs ocultos)...")
        if MODO_TESTE_SOZINHO:
            print("⚠️ ATENÇÃO: MODO DE TESTE ATIVADO (ALTERNÂNCIA FORÇADA) ⚠️")

        self.model = Model(model_path)
        self.spk_model = SpkModel(spk_model_path)

        # INTEGRAÇÃO: Instancia o Transcritor reutilizável
        self.transcritor_google = TranscritorVoz(idioma="pt-BR")

    def _normalizar_audio(self, raw_frames, sampwidth):
        try:
            peak = audioop.max(raw_frames, sampwidth)
            if peak == 0: return raw_frames
            max_possible = 2 ** (8 * sampwidth - 1) - 1
            scale_factor = min(max_possible / peak, 5.0)
            return audioop.mul(raw_frames, sampwidth, scale_factor)
        except:
            return raw_frames

    def processar_audio(self, audio_path):
        try:
            wf = wave.open(audio_path, "rb")
        except wave.Error:
            raise ValueError("Arquivo WAV inválido.")

        # 1. Leitura
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        wf.close()

        # 2. Pré-processamento
        audio_mono = frames
        if n_channels > 1:
            audio_mono = audioop.tomono(frames, sampwidth, 1, 1)

        target_rate = 16000
        if framerate != target_rate:
            audio_mono, _ = audioop.ratecv(audio_mono, sampwidth, 1, framerate, target_rate, None)

        audio_mono = self._normalizar_audio(audio_mono, sampwidth)

        # 3. Extração Vosk (Segmentação)
        rec = KaldiRecognizer(self.model, target_rate, self.spk_model)
        rec.SetWords(True)


        raw_segments = []
        step = 4000

        for i in range(0, len(audio_mono), step):
            data = audio_mono[i:i + step]

            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())

                # Preserva o texto mesmo quando não existe vetor de falante.
                if res.get('result') and res.get('text', '').strip():
                    raw_segments.append(res)

        # Finaliza o reconhecimento somente depois de processar todo o áudio.
        res_final = json.loads(rec.FinalResult())

        if res_final.get('result') and res_final.get('text', '').strip():
            raw_segments.append(res_final)


        # 4. Fusão e Classificação
        merged_segments = self._mesclar_e_classificar(raw_segments)

        # 5. Transcrição Final (Usa a classe integrada)
        print(f"[AUDIO_SERVICE] Transcrevendo {len(merged_segments)} blocos via TranscritorVoz...")

        with open(audio_path, 'rb') as f:
            raw_wav_data = f.read()

        header_size = 44
        raw_pcm = raw_wav_data[header_size:]
        bytes_per_second = framerate * sampwidth * n_channels
        total_bytes = len(raw_pcm)

        final_dialogue = []

        for seg in merged_segments:
            padding = 0.4
            start_byte = int(max(0, seg['start'] - padding) * bytes_per_second)
            start_byte -= start_byte % (sampwidth * n_channels)

            end_byte = int((seg['end'] + padding) * bytes_per_second)
            end_byte -= end_byte % (sampwidth * n_channels)
            if end_byte > total_bytes: end_byte = total_bytes

            chunk_data = raw_pcm[start_byte:end_byte]

            if len(chunk_data) < 3200: continue

            # Cria objeto para o TranscritorVoz
            audio_chunk = sr.AudioData(chunk_data, framerate, sampwidth)

            # --- USO DA INTEGRAÇÃO ---
            # Chama a classe especializada em vez de fazer try/except aqui
            texto_google = self.transcritor_google.transcrever(audio_chunk)

            # Lógica de Fallback
            if texto_google:
                text_final = texto_google
            else:
                # Se Google falhou (retornou None), usa texto do Vosk acumulado
                text_final = seg.get('text_combined', '')

            if text_final and len(text_final.strip()) > 1:
                text_final = text_final[0].upper() + text_final[1:]

                final_dialogue.append({
                    "role": seg['role'],
                    "role_key": seg['role_key'],
                    "text": text_final,
                    "speaker_id": seg['speaker_id']
                })

        full_text = "\n".join([f"{d['role']}: {d['text']}" for d in final_dialogue])
        unique_ids = {d['speaker_id'] for d in final_dialogue}

        return {
            "full_text": full_text,
            "dialogue": final_dialogue,
            "speakers_count": len(unique_ids)
        }


    def _mesclar_e_classificar(self, raw_segments):
        """
        Agrupa segmentos de áudio sem descartar texto quando falta
        o vetor de identificação do falante.

        A identidade vocal pode ser estimada pelos vetores disponíveis,
        mas a função clínica (médico/paciente) não é inferida.
        """
        if not raw_segments:
            return []

        MAX_SILENCE = 1.5
        SIMILARITY_THRESHOLD = 0.8
        merged = []

        for raw in raw_segments:
            # Ignora resultados sem palavras ou tempos utilizáveis.
            words = raw.get("result") or []
            text = (raw.get("text") or "").strip()

            if not words or not text:
                continue

            try:
                start = float(words[0]["start"])
                end = float(words[-1]["end"])
            except (KeyError, TypeError, ValueError, IndexError):
                continue

            if end < start:
                continue

            # O vetor de falante pode não existir.
            spk = raw.get("spk")
            try:
                vec = np.asarray(spk, dtype=float) if spk is not None else None
                if vec is not None and (vec.size == 0 or not np.all(np.isfinite(vec))):
                    vec = None
            except (TypeError, ValueError):
                vec = None

            current = {
                "start": start,
                "end": end,
                "text_combined": text,
                "spk_vec": vec.copy() if vec is not None else None,
                "count": 1,
            }

            if merged:
                previous = merged[-1]
                silence = start - previous["end"]
                prev_vec = previous["spk_vec"]

                should_merge = False

                if 0 <= silence < MAX_SILENCE:
                    if prev_vec is None and vec is None:
                        # Sem vetores, juntar texto próximo não significa
                        # que sabemos quem falou.
                        should_merge = True
                    elif prev_vec is not None and vec is not None:
                        if prev_vec.shape == vec.shape:
                            avg_vec = prev_vec / previous["count"]
                            distance = np.linalg.norm(avg_vec - vec)
                            should_merge = distance < SIMILARITY_THRESHOLD

                if should_merge:
                    previous["end"] = end
                    previous["text_combined"] += " " + text

                    if vec is not None:
                        if previous["spk_vec"] is None:
                            previous["spk_vec"] = vec.copy()
                            previous["count"] = 1
                        else:
                            previous["spk_vec"] += vec
                            previous["count"] += 1
                    continue

            merged.append(current)

        # Agrupa vetores semelhantes, quando disponíveis.
        known_speakers = []
        GLOBAL_THRESHOLD = 0.75

        for block in merged:
            vec = block["spk_vec"]

            if vec is None:
                block["speaker_id"] = None
                block["role"] = "Falante não identificado"
                block["role_key"] = "unknown"
                block.pop("spk_vec", None)
                block.pop("count", None)
                continue

            final_vec = vec / max(block["count"], 1)
            best_idx = -1
            min_dist = float("inf")

            for idx, known_vec in enumerate(known_speakers):
                if final_vec.shape != known_vec.shape:
                    continue

                distance = np.linalg.norm(final_vec - known_vec)
                if distance < min_dist:
                    min_dist = distance
                    best_idx = idx

            if best_idx != -1 and min_dist < GLOBAL_THRESHOLD:
                speaker_id = best_idx
                known_speakers[best_idx] = (
                    known_speakers[best_idx] * 0.8 + final_vec * 0.2
                )
            else:
                known_speakers.append(final_vec.copy())
                speaker_id = len(known_speakers) - 1

            # Distinguir vozes não comprova quem é médico ou paciente.
            block["speaker_id"] = speaker_id
            block["role"] = f"Falante {speaker_id + 1} (função não identificada)"
            block["role_key"] = "unknown"

            block.pop("spk_vec", None)
            block.pop("count", None)

        return merged
