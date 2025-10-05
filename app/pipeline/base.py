# app/pipeline/base.py

from abc import ABC, abstractmethod

class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, audio_path, language=None):
        pass

class Translator(ABC):
    @abstractmethod
    def translate(self, text,src_lang, target_lang):
        pass
