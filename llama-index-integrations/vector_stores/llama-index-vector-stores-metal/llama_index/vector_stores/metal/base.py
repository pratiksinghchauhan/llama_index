import math
from typing import Any, List

import metal_sdk  # noqa
from llama_index.core.schema import BaseNode, MetadataMode, TextNode
from llama_index.core.vector_stores.types import (
    MetadataFilters,
    BasePydanticVectorStore,
    VectorStoreQuery,
    VectorStoreQueryResult,
)
from llama_index.core.vector_stores.utils import (
    legacy_metadata_dict_to_node,
    metadata_dict_to_node,
    node_to_metadata_dict,
)
from metal_sdk.metal import Metal


def _to_metal_filters(standard_filters: MetadataFilters) -> list:
    filters = []
    for filter in standard_filters.legacy_filters():
        filters.append(
            {
                "field": filter.key,
                "value": filter.value,
            }
        )
    return filters


class MetalVectorStore(BasePydanticVectorStore):
    """Metal Vector Store.

    Examples:
        `pip install llama-index-vector-stores-metal`

        ```python
        from llama_index.vector_stores.metal import MetalVectorStore

        # Sign up for Metal and generate API key and client ID
        api_key = "your_api_key_here"
        client_id = "your_client_id_here"
        index_id = "your_index_id_here"

        # Initialize Metal Vector Store
        vector_store = MetalVectorStore(
            api_key=api_key,
            client_id=client_id,
            index_id=index_id,
        )
        ```
    """

    stores_text: bool = True
    flat_metadata: bool = False
    is_embedding_query: bool = True

    api_key: str
    client_id: str
    index_id: str
    metal_client: Metal

    def __init__(
        self,
        api_key: str,
        client_id: str,
        index_id: str,
    ):
        """Init params."""
        super().__init__(
            api_key=api_key,
            client_id=client_id,
            index_id=index_id,
            metal_client=Metal(api_key, client_id, index_id),
        )

    @classmethod
    def class_name(cls) -> str:
        return "MetalVectorStore"

    def query(self, query: VectorStoreQuery, **kwargs: Any) -> VectorStoreQueryResult:
        if query.filters is not None:
            if "filters" in kwargs:
                raise ValueError(
                    "Cannot specify filter via both query and kwargs. "
                    "Use kwargs only for metal specific items that are "
                    "not supported via the generic query interface."
                )
            filters = _to_metal_filters(query.filters)
        else:
            filters = kwargs.get("filters", {})

        payload = {
            "embedding": query.query_embedding,  # Query Embedding
            "filters": filters,  # Metadata Filters
        }
        response = self.metal_client.search(payload, limit=query.similarity_top_k)

        nodes = []
        ids = []
        similarities = []

        for item in response["data"]:
            text = item["text"]
            id_ = item["id"]

            # load additional Node data
            try:
                node = metadata_dict_to_node(item["metadata"])
                node.text = text
            except Exception:
                # NOTE: deprecated legacy logic for backward compatibility
                metadata, node_info, relationships = legacy_metadata_dict_to_node(
                    item["metadata"]
                )

                node = TextNode(
                    text=text,
                    id_=id_,
                    metadata=metadata,
                    start_char_idx=node_info.get("start", None),
                    end_char_idx=node_info.get("end", None),
                    relationships=relationships,
                )

            nodes.append(node)
            ids.append(id_)

            similarity_score = 1.0 - math.exp(-item["dist"])
            similarities.append(similarity_score)

        return VectorStoreQueryResult(nodes=nodes, similarities=similarities, ids=ids)

    @property
    def client(self) -> Any:
        """Return Metal client."""
        return self.metal_client

    def add(self, nodes: List[BaseNode], **add_kwargs: Any) -> List[str]:
        """Add nodes to index.

        Args:
            nodes: List[BaseNode]: list of nodes with embeddings.

        """
        if not self.metal_client:
            raise ValueError("metal_client not initialized")

        ids = []
        for node in nodes:
            ids.append(node.node_id)

            metadata = {}
            metadata["text"] = node.get_content(metadata_mode=MetadataMode.NONE) or ""

            additional_metadata = node_to_metadata_dict(
                node, remove_text=True, flat_metadata=self.flat_metadata
            )
            metadata.update(additional_metadata)

            payload = {
                "embedding": node.get_embedding(),
                "metadata": metadata,
                "id": node.node_id,
            }

            self.metal_client.index(payload)

        return ids

    def delete(self, ref_doc_id: str, **delete_kwargs: Any) -> None:
        """
        Delete nodes using with ref_doc_id.

        Args:
            ref_doc_id (str): The doc_id of the document to delete.

        """
        if not self.metal_client:
            raise ValueError("metal_client not initialized")

        self.metal_client.deleteOne(ref_doc_id)
