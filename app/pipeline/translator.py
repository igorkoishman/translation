from .base import Translator
from transformers import pipeline as hf_pipeline



# class LocalLLMTranslate(Translator):
#     MODEL_MAP = {
#         ("en", "he"): ("translation_en_to_he", "Helsinki-NLP/opus-mt-en-he"),
#         ("en", "ru"): ("translation_en_to_ru", "Helsinki-NLP/opus-mt-en-ru"),
#         ("en", "es"): ("translation_en_to_es", "Helsinki-NLP/opus-mt-en-es"),
#         ("en", "ar"): ("translation_en_to_ar", "Helsinki-NLP/opus-mt-en-ar"),
#         ("ru", "en"): ("translation_ru_to_en", "Helsinki-NLP/opus-mt-ru-en"),
#         ("es", "en"): ("translation_es_to_en", "Helsinki-NLP/opus-mt-es-en"),
#         ("ar", "en"): ("translation_ar_to_en", "Helsinki-NLP/opus-mt-ar-en"),
#     }
#     _pipeline_cache = {}  # static/shared cache for loaded pipelines
#
#     def translate(self, text, target_lang, src_lang):
#         key = (src_lang.lower(), target_lang.lower())
#         if key not in self.MODEL_MAP:
#             raise ValueError(f"No local model for {src_lang} to {target_lang}")
#         if key not in self._pipeline_cache:
#             pipeline_task, model_name = self.MODEL_MAP[key]
#             self._pipeline_cache[key] = hf_pipeline(pipeline_task, model=model_name)
#         translator = self._pipeline_cache[key]
#         result = translator(text)
#         return result[0]["translation_text"]


class LocalLLMTranslate(Translator):
    _pipeline_cache = {}  # static/shared cache for loaded pipelines

    def translate(self, text,  src_lang,target_lang):
        src = src_lang.lower()
        tgt = target_lang.lower()
        model_name = f"Helsinki-NLP/opus-mt-{src}-{tgt}"
        pipeline_task = f"translation_{src}_to_{tgt}"
        key = (src, tgt)
        if key not in self._pipeline_cache:
            try:
                self._pipeline_cache[key] = hf_pipeline(pipeline_task, model=model_name)
            except Exception as e:
                raise ValueError(f"Could not load HuggingFace model {model_name}: {e}")
        translator = self._pipeline_cache[key]
        result = translator(text)
        return result[0]["translation_text"]