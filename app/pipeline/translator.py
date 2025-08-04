import srt

from .base import Translator
from transformers import pipeline as hf_pipeline

class LocalLLMTranslate(Translator):
    _pipeline_cache = {}

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