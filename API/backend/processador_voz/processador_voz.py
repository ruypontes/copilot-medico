import speech_recognition as sr
import re

class CapturaAudio:
    """
    Classe responsável por capturar o áudio do microfone em tempo real.
    """
    def __init__(self):
        self.reconhecedor = sr.Recognizer()
        self.microfone = sr.Microphone()
        self.reconhecedor.pause_threshold = 0.8
        self.reconhecedor.dynamic_energy_threshold = True

    def iniciar_escuta(self):
        """Ajusta o reconhecedor para o ruído ambiente e inicia a escuta."""
        with self.microfone as source:
            self.reconhecedor.adjust_for_ambient_noise(source)
        print("Módulo de áudio iniciado. Aguardando paciente...")

    def escutar_usuario(self):
        """
        Captura o áudio do microfone e o retorna como um objeto AudioData.
        Retorna None se houver erro na captura.
        """
        try:
            with self.microfone as source:
                audio = self.reconhecedor.listen(source)
                return audio
        except sr.UnknownValueError:
            print("Não foi possível entender o áudio.")
            return None
        except sr.RequestError as e:
            print(f"Erro ao solicitar resultados do serviço de reconhecimento de fala; {e}")
            return None
        except Exception as e:
            print(f"Ocorreu um erro inesperado na captura de áudio: {e}")
            return None

class TranscritorVoz:
    """
    Classe reutilizável para transcrever áudio usando Google Speech Recognition.
    """

    # B36 / US016-CA004: chamado como auditor("google_sr", bytes_de_audio) ANTES de
    # cada envio ao Google. E atributo de CLASSE de proposito: o Diarizador cria o
    # proprio TranscritorVoz por dentro, entao registrar por instancia nao alcancaria
    # os envios dele. Aqui e o unico lugar do projeto que chama recognize_google.
    # Acessar por `TranscritorVoz.auditor` (na classe) devolve a funcao sem vincula-la.
    auditor = None

    def __init__(self, idioma="pt-BR"):
        self.reconhecedor = sr.Recognizer()
        self.idioma = idioma

    def transcrever(self, audio_data):
        """
        Transcreve AudioData para texto.
        Retorna string com erro se falhar, para logs visuais.
        """
        if not isinstance(audio_data, sr.AudioData):
            return "Erro: Dados de áudio inválidos."

        self._auditar_envio(audio_data)
        try:
            texto = self.reconhecedor.recognize_google(audio_data, language=self.idioma)
            return texto
        except sr.UnknownValueError:
            return None # Retorna None para facilitar fallback
        except sr.RequestError as e:
            print(f"Erro na API Google: {e}")
            return None
        except Exception as e:
            print(f"Erro inesperado na transcrição: {e}")
            return None

    @staticmethod
    def _auditar_envio(audio_data):
        auditor = TranscritorVoz.auditor
        if auditor is None:
            return
        try:
            auditor("google_sr", len(audio_data.frame_data))
        except Exception as erro:
            # A auditoria nunca pode impedir a transcricao. Loga so o TIPO do erro:
            # nada do que seria enviado vai para o log.
            print(f"[AUDITORIA] Falha ao registrar envio ao Google SR: {type(erro).__name__}")

class ConstrutorContexto:
    """
    Classe responsável por construir um contexto a partir do texto transcrito
    para ser processado por um LLM.
    """
    def __init__(self, id_paciente, nome_paciente):
        self.id_paciente = id_paciente
        self.nome_paciente = nome_paciente
        self.historico_conversa = []

    def adicionar_ao_historico(self, texto):
        self.historico_conversa.append(texto)

    def construir_contexto(self, texto_recente):
        self.adicionar_ao_historico(texto_recente)
        return {
            "paciente": {"id": self.id_paciente, "nome": self.nome_paciente},
            "transcricao_recente": texto_recente,
            "historico_completo": " ".join(self.historico_conversa),
            "palavras_chave": self._extrair_palavras_chave(texto_recente)
        }

    def _extrair_palavras_chave(self, texto):
        stop_words = set(["a", "o", "e", "é", "de", "do", "da", "para", "com", "em", "um", "uma", "que"])
        palavras = re.findall(r'\b\w+\b', texto.lower())
        return [p for p in palavras if p not in stop_words and len(p) > 4]
