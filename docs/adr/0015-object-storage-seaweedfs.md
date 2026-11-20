# ADR-0015: S3-compatible object storage; SeaweedFS in the dev stack

- Status: Accepted
- Date: 2026-11-20

## Context
Call recordings (and later exports) need object storage. LiveKit egress writes recordings to any S3-compatible API. The architecture originally named MinIO for local development. By November 2026 the `minio/minio` repository no longer exists on Docker Hub, and `quay.io/minio/minio` publishes no tags. The community edition is no longer distributed as maintained images.

## Decision
- Ringbridge talks to object storage only through the **S3 API** (endpoint, bucket, access key, secret, region). AWS S3, Cloudflare R2, Google Cloud Storage (S3 interop), Backblaze B2 and self-hosted stores all work.
- The local dev stack uses **SeaweedFS** (`chrislusf/seaweedfs`, Apache-2.0, actively released) in single-container mode with its S3 gateway and a dev-only identity.

## Alternatives considered
- **An old pinned MinIO image.** Unmaintained, so it would receive no security fixes.
- **Garage.** Lightweight and S3-compatible, but AGPL. That is fine for a dev dependency, but it is less familiar to most contributors.
- **No object storage until M2.** Recordings arrive in #27, but having the service in the stack now keeps the stack stable once code depends on it.

## Consequences
No code may depend on SeaweedFS-specific features. #27 must test recordings against both SeaweedFS and one hosted S3 provider.
