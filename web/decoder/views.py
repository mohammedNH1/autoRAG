"""
decoder/views.py
-----------------
Django REST views for the decoder LLM app.

Endpoints
---------
POST /decoder/generate/   — accepts a pre-built prompt OR query+context
GET  /decoder/info/       — returns model metadata
"""

import json
import logging

from django.http                  import JsonResponse
from django.views                 import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators      import method_decorator

from .inference import RAGInference

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Singleton engine
# ---------------------------------------------------------------------------
# To load a trained model, add this to your Django settings.py:
#   DECODER_CHECKPOINT = "checkpoints/decoder_v1"
# Leave unset to use a fresh (untrained) model during development.

def get_engine() -> RAGInference:
    from django.conf import settings
    checkpoint = getattr(settings, "DECODER_CHECKPOINT", None)
    return RAGInference.get_instance(checkpoint_path=checkpoint)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class GenerateView(View):
    """
    POST /decoder/generate/

    Accepts either:
      (A) A fully pre-built prompt from your RAG pipeline:
          { "prompt": "<full prompt string>", ... }

      (B) Query + context (the view builds the prompt):
          { "query": "...", "retrieved_context": "...", ... }

    Optional fields (all have defaults):
        max_new_tokens  : int   (default 200)
        temperature     : float (default 0.8)
        top_p           : float (default 0.9)
        top_k           : int   (default 40)

    Response
    --------
    { "answer": "...", "prompt_tokens": <int> }
    """

    def post(self, request, *args, **kwargs):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        # --- Resolve the prompt ---
        prompt = body.get("prompt", "").strip()

        if not prompt:
            # Fallback: build from query + context
            query = body.get("query", "").strip()
            if not query:
                return JsonResponse(
                    {"error": "Provide either 'prompt' or 'query'."},
                    status=400,
                )
            context = body.get("retrieved_context", "").strip()
            if context:
                prompt = (
                    f"Answer the following question based on the context below.\n\n"
                    f"Context:\n{context}\n\n"
                    f"Question: {query}"
                )
            else:
                prompt = f"Question: {query}"

        max_new_tokens = int(body.get("max_new_tokens", 200))
        temperature    = float(body.get("temperature", 0.8))
        top_p          = float(body.get("top_p", 0.9))
        top_k          = int(body.get("top_k", 40))

        engine = get_engine()

        try:
            answer = engine.generate_from_prompt(
                prompt         = prompt,
                max_new_tokens = max_new_tokens,
                temperature    = temperature,
                top_p          = top_p,
                top_k          = top_k,
            )
        except Exception as exc:
            logger.exception("[decoder] Generation failed")
            return JsonResponse({"error": str(exc)}, status=500)

        prompt_tokens = len(engine.tokenizer.encode(prompt, add_special_tokens=False))
        return JsonResponse(
            {"answer": answer, "prompt_tokens": prompt_tokens},
            status=200,
        )


@method_decorator(csrf_exempt, name="dispatch")
class ModelInfoView(View):
    """
    GET /decoder/info/
    Returns parameter count, tokenizer info, and model config.
    """

    def get(self, request, *args, **kwargs):
        engine = get_engine()
        return JsonResponse(engine.model_info(), status=200)