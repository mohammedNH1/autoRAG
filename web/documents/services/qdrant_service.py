"""
Here is the vector DATABASE
"""

from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
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

from model_selector import ModelSelector, EmbeddingModelConfig

logger = logging.getLogger(__name__)


class QdrantService:

    """
   Saves vectors to Qdrant database and searches them by similarity.
    """
    
    def __init__(self, host: str = "localhost", port: int = 6333):

        """
        Connect to Qdrant
        """
        self.client = QdrantClient(host=host, port=port)
        logger.info(f" Connected to Qdrant at {host}:{port}")
    
    def ensure_collection(self, model_config: EmbeddingModelConfig) -> str:

        """
        Create collection if it doesn't exist, or validate existing one.
        
        separate collections per model (Because every collection has diff vector demnsion)
        """
        collection_name = ModelSelector.get_collection_name(model_config.collection_key)
        
        # Check if collection exists
        collections = self.client.get_collections().collections
        collection_exists = any(c.name == collection_name for c in collections)
        
        if collection_exists:
            # Validate dimension matches
            collection_info = self.client.get_collection(collection_name)
            existing_dim = collection_info.config.params.vectors.size
            
            if existing_dim != model_config.dimension:
                raise ValueError(
                    f" Collection {collection_name} has dimension {existing_dim}, "
                    f"but model {model_config.model_name} requires {model_config.dimension}. "
                    f"This workspace's model changed. Consider re-indexing all documents."
                )
            
            logger.debug(f" Collection {collection_name} exists (dim={existing_dim})")
        else:
            # Create new collection with correct dimension
            logger.info(
                f"🆕 Creating collection {collection_name} "
                f"(dim={model_config.dimension}, distance=COSINE)"
            )
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=model_config.dimension,
                    distance=Distance.COSINE,  # Best for normalized embeddings
                ),
            )
            logger.info(f" Collection {collection_name} created")
        
        return collection_name
    
    def index_document_chunk(
        self,
        collection_name: str,
        workspace_id: int,
        document_id: int,
        chunk_id: int,
        text: str,
        vector: List[float],
        additional_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Store a single document chunk with workspace isolation.
        Args:
            collection_name: Target collection
            workspace_id: Workspace ID (for isolation)
            document_id: Document ID from Document model
            chunk_id: Chunk number within document
            text: Original text content
            vector: Embedding vector
            additional_metadata: Optional extra fields (title, page, etc.)
        
        Returns:
            Generated point ID (UUID) (examplw :"uuid-123")
        """
        # Generate unique point ID
        point_id = str(uuid.uuid4())
        
        # Build payload with mandatory workspace_id for isolation
        payload = {
            "workspace_id": workspace_id,  # Workspace isolation
            "document_id": document_id,
            "chunk_id": chunk_id,
            "text": text,
        }
        
        # Add optional metadata
        if additional_metadata:
            payload.update(additional_metadata)
        
        # Create point
        point = PointStruct(
            id=point_id,
            vector=vector,
            payload=payload,
        )
        
        # Upsert to Qdrant
        self.client.upsert(
            collection_name=collection_name,
            points=[point],
        )
        
        logger.debug(
            f"📥 Indexed chunk {chunk_id} of doc {document_id} "
            f"for workspace {workspace_id}"
        )
        return point_id
    
    def search(
        self,
        collection_name: str,
        workspace_id: int,
        query_vector: List[float],
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors with MANDATORY workspace isolation.
        
        SECURITY: Always filters by workspace_id.
        Users can only search within their workspace.
        
        Args:
            collection_name: Collection to search
            workspace_id: Workspace ID (from workspace object)
            query_vector: Query embedding vector
            top_k: Number of results to return
            score_threshold: Optional minimum similarity score (0-1)
        
        Returns:
            List of results with score and payload
        """
 
        workspace_filter = Filter(
            must=[
                FieldCondition(
                    key="workspace_id",
                    match=MatchValue(value=workspace_id),
                )
            ]
        )
        
        # Execute search with mandatory filter
        search_result = self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=workspace_filter,  # Enforces workspace isolation
            limit=top_k,
            score_threshold=score_threshold,
        ).points
        
        # Format results
        results = []
        for scored_point in search_result:
            results.append({
                "id": scored_point.id,
                "score": scored_point.score,
                "payload": scored_point.payload,
            })
        
        logger.debug(f"🔍 Found {len(results)} results for workspace {workspace_id}")
        return results
    
    def delete_document(
        self,
        collection_name: str,
        workspace_id: int,
        document_id: int,
    ) -> int:
        """
        Delete all chunks of a document within a workspace.
        
        Args:
            collection_name: Collection name
            workspace_id: Workspace ID
            document_id: Document ID to delete
        
        Returns:
            Number of points deleted
        """
        # Filter: workspace_id AND document_id
        delete_filter = Filter(
            must=[
                FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]
        )
        
        # Delete matching points
        result = self.client.delete(
            collection_name=collection_name,
            points_selector=delete_filter,
        )
        
        logger.info(f" Deleted document {document_id} from workspace {workspace_id}")
        return result
    
     
    def get_document_chunks(    #Note my pal told me to put it , but i sufferd to know what its purpose, i kept some of the Ai comments for u to understand well the structre of the functions.
        self,
        collection_name: str,
        workspace_id: int,
        document_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all chunks of a document.
        
        Useful for:
        - Verifying indexing
        - Debugging
        - Re-indexing
        
        Args:
            collection_name: Collection name
            workspace_id: Workspace ID
            document_id: Document ID
        
        Returns:
            List of chunks with payloads
        """
        # Scroll through all points matching filter
        filter_condition = Filter(
            must=[
                FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]
        )
        
        points, _ = self.client.scroll(
            collection_name=collection_name,
            scroll_filter=filter_condition,
            limit=1000,  # Adjust if documents have more chunks
        )
        
        return [
            {
                "id": point.id,
                "payload": point.payload,
                "vector": point.vector,
            }
            for point in points
        ]
