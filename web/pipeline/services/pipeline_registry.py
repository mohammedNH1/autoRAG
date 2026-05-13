import logging
import threading

from sentence_transformers import CrossEncoder, SentenceTransformer


logger = logging.getLogger(__name__)

pipeline_registry = {}

# Tracks workspace_ids currently being pre-warmed so two concurrent visits
# don't both spawn a loader thread (which would double VRAM during load).
_warming = set()
_warming_lock = threading.Lock()


def build_pipeline(config):
    return {
        "embedding_model": SentenceTransformer(config.embedding_model),
        "reranker":        CrossEncoder(config.re_ranker),
        "temperature":     config.temperature,
        "top_p":           config.top_p,
        "top_k":           config.top_k,
    }


def get_pipeline(workspace_id, config):
    """Load + cache the pipeline for `workspace_id`. Blocks on first call."""
    if workspace_id not in pipeline_registry:
        pipeline_registry[workspace_id] = build_pipeline(config)
    return pipeline_registry[workspace_id]


def warm_pipeline_async(workspace_id, config):
    """
    Kick off pipeline loading in a background thread and return immediately.

    Safe to call repeatedly — already-loaded or currently-loading workspaces
    are skipped. By the time the user submits their first query, the
    embedding + reranker models are usually already in RAM.
    """
    if workspace_id in pipeline_registry:
        return

    with _warming_lock:
        if workspace_id in _warming or workspace_id in pipeline_registry:
            return
        _warming.add(workspace_id)

    def _load():
        try:
            get_pipeline(workspace_id, config)
        except Exception:
            logger.exception("Pipeline pre-warm failed for workspace %s", workspace_id)
        finally:
            with _warming_lock:
                _warming.discard(workspace_id)

    threading.Thread(
        target=_load,
        daemon=True,
        name=f"pipeline-warm-{workspace_id}",
    ).start()


def invalidate_pipeline(workspace_id):
    if workspace_id in pipeline_registry:
        del pipeline_registry[workspace_id]
