from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Iterable

from azure.core.exceptions import ResourceExistsError
from azure.identity import AzureCliCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from backend.core.config import settings


def _supports_storage_sdk_connection_string(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    if normalized.lower().startswith("resourceid="):
        return False
    return True


class BaseBlobStore:
    def __init__(
        self,
        *,
        container_name: str,
        connection_string: str = "",
        account_url: str = "",
        account_key: str = "",
    ) -> None:
        resolved_connection_string = connection_string.strip()
        if _supports_storage_sdk_connection_string(resolved_connection_string):
            self._client = BlobServiceClient.from_connection_string(resolved_connection_string)
        else:
            credential = account_key or AzureCliCredential()
            self._client = BlobServiceClient(
                account_url=account_url or settings.azure_blob_account_url,
                credential=credential,
            )
        self.container_name = container_name

    def ensure_container(self) -> None:
        try:
            self._client.create_container(self.container_name)
        except ResourceExistsError:
            return

    def list_blobs(self, *, prefix: str | None = None) -> list[str]:
        self.ensure_container()
        return [
            blob.name
            for blob in self._client.get_container_client(self.container_name).list_blobs(
                name_starts_with=prefix or None
            )
        ]

    def upload_file(
        self,
        path: Path,
        *,
        blob_name: str,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, str]:
        self.ensure_container()
        blob_client = self._client.get_blob_client(container=self.container_name, blob=blob_name)
        content_type, _ = mimetypes.guess_type(path.name)
        content_settings = ContentSettings(content_type=content_type or "application/octet-stream")
        with path.open("rb") as handle:
            blob_client.upload_blob(
                handle,
                overwrite=True,
                metadata=metadata,
                content_settings=content_settings,
            )
        return {
            "blob_name": blob_name,
            "blob_url": blob_client.url,
            "content_type": content_settings.content_type or "application/octet-stream",
        }

    def upload_bytes(
        self,
        payload: bytes,
        *,
        blob_name: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, str]:
        self.ensure_container()
        blob_client = self._client.get_blob_client(container=self.container_name, blob=blob_name)
        blob_client.upload_blob(
            payload,
            overwrite=True,
            metadata=metadata,
            content_settings=ContentSettings(content_type=content_type),
        )
        return {
            "blob_name": blob_name,
            "blob_url": blob_client.url,
            "content_type": content_type,
        }

    def download_bytes(self, blob_name: str) -> tuple[bytes, str]:
        blob_client = self._client.get_blob_client(container=self.container_name, blob=blob_name)
        downloader = blob_client.download_blob()
        # The downloader already carries the blob's properties from the initial
        # response, so read the content type from there instead of issuing a
        # second round trip via get_blob_properties().
        content_settings = getattr(downloader.properties, "content_settings", None)
        content_type = (content_settings.content_type if content_settings else None) or "application/octet-stream"
        return downloader.readall(), content_type

    def delete_blob(self, blob_name: str) -> None:
        blob_client = self._client.get_blob_client(container=self.container_name, blob=blob_name)
        blob_client.delete_blob(delete_snapshots="include")


class BlobArtifactStore(BaseBlobStore):
    def __init__(self) -> None:
        super().__init__(
            container_name=settings.azure_storage_container,
            connection_string=settings.azure_storage_connection_string,
            account_url=settings.azure_blob_account_url,
            account_key=settings.azure_storage_account_key,
        )


class BlobDocumentStore(BaseBlobStore):
    def __init__(self) -> None:
        super().__init__(
            container_name=settings.azure_search_blob_source_container,
            connection_string=settings.azure_search_blob_connection_string_resolved,
            account_url=settings.azure_blob_account_url,
            account_key=settings.azure_storage_account_key,
        )


class BlobSearchAssetStore(BaseBlobStore):
    def __init__(self) -> None:
        super().__init__(
            container_name=settings.azure_search_asset_store_container,
            connection_string=(
                settings.azure_search_asset_store_connection_string
                or settings.azure_search_blob_connection_string_resolved
            ),
            account_url=settings.azure_blob_account_url,
            account_key=settings.azure_storage_account_key,
        )


def build_blob_artifact_store() -> BlobArtifactStore | None:
    if not settings.azure_blob_storage_enabled:
        return None
    return BlobArtifactStore()


def build_blob_document_store() -> BlobDocumentStore | None:
    if not settings.azure_search_blob_ingestion_enabled:
        return None
    return BlobDocumentStore()


def build_blob_search_asset_store() -> BlobSearchAssetStore | None:
    if not (
        settings.azure_search_enable_image_serving
        and settings.azure_search_asset_store_container
        and (settings.azure_search_asset_store_connection_string or settings.azure_search_blob_connection_string_resolved)
    ):
        return None
    global _BLOB_SEARCH_ASSET_STORE
    if _BLOB_SEARCH_ASSET_STORE is None:
        # Reuse a single store (and its BlobServiceClient / AzureCliCredential) across
        # requests. AzureCliCredential caches access tokens in-memory per instance, so
        # sharing it avoids a fresh `az` token shell-out on every image fetch — the main
        # source of the multi-second latency when serving native crops.
        _BLOB_SEARCH_ASSET_STORE = BlobSearchAssetStore()
    return _BLOB_SEARCH_ASSET_STORE


_BLOB_SEARCH_ASSET_STORE: BlobSearchAssetStore | None = None
