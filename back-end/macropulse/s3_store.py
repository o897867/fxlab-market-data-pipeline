"""S3 raw 层读写 + 幂等清单（manifest）。

清单结构（存于 metadata/macro_ingest_manifest.json）：
  {
    "documents": {
      "fed_statement_2026-04-29": {
        "content_hash": "sha256:...",
        "json_key": "raw/macro/fed/statement/year=2026/fed_statement_2026-04-29.json",
        "html_key": "raw/macro/fed/statement/year=2026/fed_statement_2026-04-29.html",
        "retrieved_at": "..."
      }
    },
    "updated_at": "..."
  }

去重 / 幂等：同一 document_id 且 content_hash 未变 → 跳过写入。
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone

import boto3

from macropulse import config
from macropulse.models import RawDocument

logger = logging.getLogger(__name__)


def raw_keys(doc: RawDocument) -> tuple[str, str]:
    """生成 (json_key, html_key)，按 bank/type/year 分区。"""
    year = doc.meeting_date[:4] if doc.meeting_date else "unknown"
    base = f"{config.RAW_MACRO_PREFIX}/{doc.central_bank.lower()}/{doc.doc_type}/year={year}/{doc.document_id}"
    return f"{base}.json", f"{base}.html"


class Manifest:
    """纯逻辑的幂等清单，便于单测（不依赖 S3）。"""

    def __init__(self, data: dict | None = None):
        data = data or {}
        self.documents: dict = data.get("documents", {})

    def is_unchanged(self, document_id: str, hash_: str) -> bool:
        rec = self.documents.get(document_id)
        return bool(rec) and rec.get("content_hash") == hash_

    def record(self, doc: RawDocument, json_key: str, html_key: str) -> None:
        self.documents[doc.document_id] = {
            "content_hash": doc.content_hash,
            "json_key": json_key,
            "html_key": html_key,
            "retrieved_at": doc.retrieved_at,
        }

    def to_dict(self) -> dict:
        return {
            "documents": self.documents,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


class S3RawStore:
    """封装 boto3 的 raw 层写入与清单读写。"""

    def __init__(self, bucket: str = None, region: str = None, client=None):
        self.bucket = bucket or config.S3_BUCKET
        self.s3 = client or boto3.client("s3", region_name=region or config.S3_REGION)

    # ---- manifest
    def load_manifest(self) -> Manifest:
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=config.MANIFEST_KEY)
            return Manifest(json.loads(obj["Body"].read()))
        except self.s3.exceptions.NoSuchKey:
            return Manifest()
        except Exception as e:  # noqa: BLE001 — 清单缺失/损坏时从空开始
            logger.warning("清单读取失败，从空开始: %s", e)
            return Manifest()

    def save_manifest(self, manifest: Manifest) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=config.MANIFEST_KEY,
            Body=json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )

    # ---- read（供 diff 等下游消费 raw 层）
    def list_statements(self) -> list[str]:
        """按会议日升序列出全部声明 .json 的 S3 key。"""
        prefix = f"{config.RAW_MACRO_PREFIX}/fed/statement/"
        keys = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for o in page.get("Contents", []):
                if o["Key"].endswith(".json"):
                    keys.append(o["Key"])
        return sorted(keys)  # key 里含 YYYY-MM-DD，字典序即时间序

    def load_json(self, key: str) -> dict:
        obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        return json.loads(obj["Body"].read())

    # ---- document
    def put_document(self, doc: RawDocument, html: str) -> tuple[str, str]:
        json_key, html_key = raw_keys(doc)
        doc.raw_html_key = html_key
        self.s3.put_object(
            Bucket=self.bucket,
            Key=json_key,
            Body=json.dumps(doc.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
        self.s3.put_object(
            Bucket=self.bucket,
            Key=html_key,
            Body=html.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
        )
        logger.info("  -> s3://%s/%s", self.bucket, json_key)
        return json_key, html_key
