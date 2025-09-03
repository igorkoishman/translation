import sys
import os
import srt
import logging

logging.basicConfig(level=logging.INFO)

from transformers import (
    pipeline as hf_pipeline,
    AutoTokenizer,
    AutoModelForSeq2SeqLM
)

from .base import Translator  # Change this import path if needed

REQUIRED_MODELS = [
    "facebook/nllb-200-distilled-600M",
    "facebook/m2m100_418M",
]

def ensure_model_downloaded(model_id, cache_dir=None):
    try:
        print(f"Ensuring model {model_id} is available locally...", flush=True)
        # Use slow tokenizer for NLLB to avoid transformers bug
        if "nllb" in model_id:
            AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir, use_fast=False)
        else:
            AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir)
        try:
            AutoModelForSeq2SeqLM.from_pretrained(model_id, cache_dir=cache_dir)
        except OSError as e:
            if "pytorch_model.bin" in str(e) and "TensorFlow weights" in str(e):
                print(f"Retrying {model_id} with from_tf=True ...", flush=True)
                AutoModelForSeq2SeqLM.from_pretrained(model_id, cache_dir=cache_dir, from_tf=True)
            else:
                raise
        print(f"Model {model_id} is ready.", flush=True)
    except Exception as e:
        print(f"Could not download or load model {model_id}: {e}", file=sys.stderr, flush=True)

def preload_models(model_dir=None):
    if model_dir is None:
        model_dir = "./model"
    if not os.path.exists(model_dir):
        os.makedirs(model_dir, exist_ok=True)
    for model_id in REQUIRED_MODELS:
        ensure_model_downloaded(model_id, cache_dir=model_dir)

def get_pipeline_with_tf_fallback(*args, **kwargs):
    # Use slow tokenizer for NLLB models (workaround for transformers bug)
    model_id = kwargs.get("model") or (args[1] if len(args) > 1 else None)
    cache_dir = kwargs.pop("cache_dir", "./model")  # REMOVE cache_dir from kwargs!
    if model_id and "nllb" in model_id:
        tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir, use_fast=False)
        kwargs["tokenizer"] = tokenizer
    try:
        return hf_pipeline(*args, **kwargs)
    except OSError as e:
        if "pytorch_model.bin" in str(e) and "TensorFlow weights" in str(e):
            print(f"Retrying pipeline with from_tf=True ...", flush=True)
            if model_id and "nllb" in model_id:
                tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir, use_fast=False)
                kwargs["tokenizer"] = tokenizer
            return hf_pipeline(*args, from_tf=True, **kwargs)
        else:
            raise

# class LocalLLMTranslate(Translator):
#     def __init__(self, model_path="./model"):
#         self._pipeline_cache = {}
#         self.MODEL_CACHE_DIR = model_path
#
#     # Add all Helsinki model variants you want to try, in priority order
#     MODEL_VARIANTS = [
#         "opus-mt-tc-big-",
#         "opus-mt-pre-",
#         "opus-mt-big-",
#         "opus-mt-"
#     ]
#
#     def translate(self, text, src_lang, target_lang):
#         src = src_lang.lower()
#         tgt = target_lang.lower()
#         attempts = []
#
#         src_codes = [src]
#         if src == "he":
#             src_codes.append("iw")
#         elif src == "iw":
#             src_codes.append("he")
#         tgt_codes = [tgt]
#         if tgt == "he":
#             tgt_codes.append("iw")
#         elif tgt == "iw":
#             tgt_codes.append("he")
#
#         tried_keys = set()
#         for src_code in src_codes:
#             for tgt_code in tgt_codes:
#                 key = (src_code, tgt_code)
#                 if key in tried_keys:
#                     continue
#                 tried_keys.add(key)
#                 for model_variant in self.MODEL_VARIANTS:
#                     model_name = f"Helsinki-NLP/{model_variant}{src_code}-{tgt_code}"
#                     pipeline_task = f"translation_{src_code}_to_{tgt_code}"
#                     if key not in self._pipeline_cache:
#                         print(f"Trying model: {model_name} ...", flush=True)
#                         try:
#                             self._pipeline_cache[key] = get_pipeline_with_tf_fallback(
#                                 pipeline_task, model=model_name, cache_dir=self.MODEL_CACHE_DIR
#                             )
#                         except Exception as e:
#                             attempts.append((pipeline_task, model_name, str(e)))
#                             print(f"Failed: {model_name} ({str(e)})", flush=True)
#                             continue
#                     translator = self._pipeline_cache.get(key)
#                     if translator:
#                         print(f"Using model: {model_name}", flush=True)
#                         result = translator(text)
#                         return result[0]["translation_text"]
#
#         raise ValueError(
#             f"Could not load any HuggingFace Helsinki-NLP model for {src_lang}→{target_lang}. "
#             f"Tried: {attempts}"
#         )
#
#     def translate_srt(self, input_srt, output_srt, src_lang, tgt_lang):
#         with open(input_srt, "r", encoding="utf-8") as f:
#             subs = list(srt.parse(f.read()))
#         translated_subs = []
#         for i, sub in enumerate(subs, 1):
#             try:
#                 print(f"Translating subtitle {i}/{len(subs)}...", flush=True)
#                 text = self.translate(sub.content, src_lang, tgt_lang)
#             except Exception as e:
#                 print(f"Translation error (subtitle {i}): {e}", flush=True)
#                 text = sub.content
#             translated_subs.append(srt.Subtitle(
#                 index=sub.index,
#                 start=sub.start,
#                 end=sub.end,
#                 content=text
#             ))
#         with open(output_srt, "w", encoding="utf-8") as f:
#             f.write(srt.compose(translated_subs))


class LocalLLMTranslate(Translator):
    def __init__(self, model_path="./model"):
        self._pipeline_cache = {}
        self.MODEL_CACHE_DIR = model_path

    def translate(self, text, src_lang,target_lang):
        src = src_lang.lower()
        tgt = target_lang.lower()
        attempts = []

        # Most common alternates for Hebrew (he/iw) and tc-big variant
        src_codes = [src]
        if src == "he":
            src_codes.append("iw")
        elif src == "iw":
            src_codes.append("he")
        tgt_codes = [tgt]
        if tgt == "he":
            tgt_codes.append("iw")
        elif tgt == "iw":
            tgt_codes.append("he")

        tried_keys = set()
        for src_code in src_codes:
            for tgt_code in tgt_codes:
                key = (src_code, tgt_code)
                if key in tried_keys:
                    continue  # Don't try same pair twice
                tried_keys.add(key)
                # Try tc-big first if Hebrew involved, then plain
                for model_variant in ["opus-mt-tc-big-", "opus-mt-"]:
                    model_name = f"Helsinki-NLP/{model_variant}{src_code}-{tgt_code}"
                    pipeline_task = f"translation_{src_code}_to_{tgt_code}"
                    if key not in self._pipeline_cache:
                        try:
                            self._pipeline_cache[key] = hf_pipeline(pipeline_task, model=model_name)
                        except Exception as e:
                            attempts.append((pipeline_task, model_name, str(e)))
                            continue
                    translator = self._pipeline_cache.get(key)
                    if translator:
                        result = translator(text)
                        return result[0]["translation_text"]

        # If we get here, all attempts failed
        raise ValueError(
            f"Could not load any HuggingFace model for {src_lang}→{target_lang}. "
            f"Tried: {attempts}"
        )
    def translate_srt(self, input_srt, output_srt, src_lang, tgt_lang):
        with open(input_srt, "r", encoding="utf-8") as f:
            subs = list(srt.parse(f.read()))
        translated_subs = []
        for sub in subs:
            try:
                text = self.translate(sub.content, src_lang, tgt_lang)
            except Exception as e:
                print(f"Translation error: {e}")
                text = sub.content
            translated_subs.append(srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=text
            ))
        with open(output_srt, "w", encoding="utf-8") as f:
            f.write(srt.compose(translated_subs))

class NLLBTranslate(Translator):
    def __init__(self, model_path="./model"):
        self._pipeline_cache = {}
        self.MODEL_CACHE_DIR = model_path

    LANG_CODE_MAP = {
        "en": "eng_Latn", "fr": "fra_Latn", "es": "spa_Latn",
        "de": "deu_Latn", "it": "ita_Latn", "ru": "rus_Cyrl",
        "he": "heb_Hebr", "ar": "arb_Arab", "iw": "heb_Hebr"
    }

    def translate(self, text, src_lang, tgt_lang):
        src_key = src_lang.lower()
        tgt_key = tgt_lang.lower()
        if src_key not in self.LANG_CODE_MAP:
            raise ValueError(
                f"NLLB: Unsupported or ambiguous src_lang '{src_lang}'. Use one of: {list(self.LANG_CODE_MAP.keys())}")
        if tgt_key not in self.LANG_CODE_MAP:
            raise ValueError(
                f"NLLB: Unsupported or ambiguous tgt_lang '{tgt_lang}'. Use one of: {list(self.LANG_CODE_MAP.keys())}")
        src = self.LANG_CODE_MAP[src_key]
        tgt = self.LANG_CODE_MAP[tgt_key]
        print(f"DEBUG: Using src={src} tgt={tgt} text='{text[:40]}...'", flush=True)
        key = (src, tgt)
        if key not in self._pipeline_cache:
            print(f"Loading NLLB model for {src}->{tgt} ...", flush=True)
            try:
                self._pipeline_cache[key] = get_pipeline_with_tf_fallback(
                    "translation",
                    model="facebook/nllb-200-distilled-600M",
                    src_lang=src,
                    tgt_lang=tgt,
                    cache_dir=self.MODEL_CACHE_DIR
                )
            except Exception as e:
                print(f"Failed to load NLLB pipeline: {e}", flush=True)
                raise ValueError(f"Failed to load NLLB pipeline: {e}")
        translator = self._pipeline_cache[key]
        result = translator(text)
        return result[0]["translation_text"]

    def translate_srt(self, input_srt, output_srt, src_lang, tgt_lang):
        with open(input_srt, "r", encoding="utf-8") as f:
            subs = list(srt.parse(f.read()))
        translated_subs = []
        for i, sub in enumerate(subs, 1):
            try:
                print(f"Translating subtitle {i}/{len(subs)}...", flush=True)
                text = self.translate(sub.content, src_lang, tgt_lang)
            except Exception as e:
                print(f"Translation error (subtitle {i}): {e}", flush=True)
                text = sub.content
            translated_subs.append(srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=text
            ))
        with open(output_srt, "w", encoding="utf-8") as f:
            f.write(srt.compose(translated_subs))

class M2M100Translate(Translator):
    def __init__(self, model_path="./model"):
        self._pipeline_cache = {}
        self.MODEL_CACHE_DIR = model_path

    LANG_CODE_MAP = {
        "en": "en", "fr": "fr", "es": "es", "de": "de", "it": "it",
        "ru": "ru", "he": "he", "ar": "ar"
    }

    def translate(self, text, src_lang, tgt_lang):
        src = self.LANG_CODE_MAP.get(src_lang.lower(), src_lang)
        tgt = self.LANG_CODE_MAP.get(tgt_lang.lower(), tgt_lang)
        key = (src, tgt)
        if key not in self._pipeline_cache:
            print(f"Loading M2M100 model for {src}->{tgt} ...", flush=True)
            try:
                self._pipeline_cache[key] = get_pipeline_with_tf_fallback(
                    "translation",
                    model="facebook/m2m100_418M",
                    src_lang=src,
                    tgt_lang=tgt,
                    cache_dir=self.MODEL_CACHE_DIR
                )
            except Exception as e:
                print(f"Failed to load M2M100 pipeline: {e}", flush=True)
                raise ValueError(f"Failed to load M2M100 pipeline: {e}")
        translator = self._pipeline_cache[key]
        result = translator(text)
        return result[0]["translation_text"]

    def translate_srt(self, input_srt, output_srt, src_lang, tgt_lang):
        with open(input_srt, "r", encoding="utf-8") as f:
            subs = list(srt.parse(f.read()))
        translated_subs = []
        for i, sub in enumerate(subs, 1):
            try:
                print(f"Translating subtitle {i}/{len(subs)}...", flush=True)
                text = self.translate(sub.content, src_lang, tgt_lang)
            except Exception as e:
                print(f"Translation error (subtitle {i}): {e}", flush=True)
                text = sub.content
            translated_subs.append(srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=text
            ))
        with open(output_srt, "w", encoding="utf-8") as f:
            f.write(srt.compose(translated_subs))

# ---- End of module ----
