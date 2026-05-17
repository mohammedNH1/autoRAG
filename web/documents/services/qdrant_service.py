from typing import Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)
import uuid
import logging

from .model_selector import ModelSelector, EmbeddingModelConfig

logger = logging.getLogger(__name__)


class QdrantService:
    """Vector storage and search backed by Qdrant."""

    def __init__(self, host: str = "localhost", port: int = 6333):
        self.client = QdrantClient(host=host, port=port)
        logger.info(f"Connected to Qdrant at {host}:{port}")

    def ensure_collection(self, model_config: EmbeddingModelConfig) -> str:
        """
        Create the Qdrant collection for the given model if it does not exist,
        or validate its vector dimension matches the model.

        Returns the collection name.
        """
        collection_name = ModelSelector.get_collection_name(model_config.collection_key)

        collections = self.client.get_collections().collections
        collection_exists = any(c.name == collection_name for c in collections)

        if collection_exists:
            collection_info = self.client.get_collection(collection_name)
            existing_dim = collection_info.config.params.vectors.size
            if existing_dim != model_config.dimension:
                raise ValueError(
                    f"Collection '{collection_name}' has dimension {existing_dim}, "
                    f"but model '{model_config.model_name}' requires {model_config.dimension}. "
                    f"Re-index all documents to use the new model."
                )
            logger.debug(f"Collection '{collection_name}' exists (dim={existing_dim})")
        else:
            logger.info(
                f"Creating collection '{collection_name}' "
                f"(dim={model_config.dimension}, distance=COSINE)"
            )
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=model_config.dimension,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Collection '{collection_name}' created")

        return collection_name

    def index_document_chunk(
        self,
        collection_name: str,
        workspace_id: int,
        document_id: int,
        chunk_id: int,
        text: str,
        vector: list[float],
        additional_metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Store a single document chunk with workspace isolation.

        Returns the generated point ID (UUID string).
        """
        point_id = str(uuid.uuid4())

        payload: dict[str, Any] = {
            "workspace_id": workspace_id,
            "document_id": document_id,
            "chunk_id": chunk_id,
            "text": text,
        }
        if additional_metadata:
            payload.update(additional_metadata)

        self.client.upsert(
            collection_name=collection_name,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

        logger.debug(
            f"Indexed chunk {chunk_id} of doc {document_id} "
            f"in workspace {workspace_id}"
        )
        return point_id

    def search(
        self,
        collection_name: str,
        workspace_id: int,
        query_vector: list[float],
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar vectors, scoped strictly to the given workspace.

        Returns a list of dicts with keys: id, score, payload.
        """
        workspace_filter = Filter(
            must=[
                FieldCondition(
                    key="workspace_id",
                    match=MatchValue(value=workspace_id),
                )
            ]
        )

        try:
            search_result = self.client.query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=workspace_filter,
                limit=top_k,
                score_threshold=score_threshold,
            ).points
        except UnexpectedResponse as exc:
            # 404 = collection doesn't exist yet. Happens when the workspace
            # config has been switched to a different embedding model but
            # no documents have been (re)indexed under the new model.
            # Treat this as "nothing to search" instead of crashing — callers
            # already handle empty results.
            if getattr(exc, "status_code", None) == 404:
                logger.warning(
                    f"Search hit missing collection '{collection_name}' "
                    f"for workspace {workspace_id} — returning no results."
                )
                return []
            raise

        results = [
            {
                "id": p.id,
                "score": p.score,
                "payload": p.payload,
            }
            for p in search_result
        ]

        logger.debug(f"Search returned {len(results)} results for workspace {workspace_id}")
        return results

    def delete_document(
        self,
        collection_name: str,
        workspace_id: int,
        document_id: int,
    ):
        """Delete all Qdrant points for a document within a workspace."""
        delete_filter = Filter(
            must=[
                FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]
        )

        result = self.client.delete(
            collection_name=collection_name,
            points_selector=delete_filter,
        )

        logger.info(f"Deleted document {document_id} from workspace {workspace_id}")
        return result

    def count_document_chunks(
        self,
        collection_name: str,
        workspace_id: int,
        document_id: int,
    ) -> int:
        """Return the number of stored chunks for a document in a workspace."""
        try:
            result = self.client.count(
                collection_name=collection_name,
                count_filter=Filter(
                    must=[
                        FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id)),
                        FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                    ]
                ),
                exact=True,
            )
            return int(result.count)
        except Exception as e:
            logger.warning(f"count_document_chunks failed for doc {document_id}: {e}")
            return 0

    def get_document_chunks(
        self,
        collection_name: str,
        workspace_id: int,
        document_id: int,
    ) -> list[dict[str, Any]]:
        """
        Retrieve all stored chunks for a document.

        Useful for verifying indexing, debugging, or re-indexing.
        """
        filter_condition = Filter(
            must=[
                FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]
        )

        points, _ = self.client.scroll(
            collection_name=collection_name,
            scroll_filter=filter_condition,
            limit=1000,
        )

        return [
            {
                "id": point.id,
                "payload": point.payload,
                "vector": point.vector,
            }
            for point in points
        ]
