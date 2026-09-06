# Large File Semantic Search

A FastAPI-based service for **resumable large-file uploads, asynchronous document processing, and semantic search** over uploaded files.

The implementation is designed for the assignment constraint of files up to **10 GB on a 4 GB RAM machine**, using streamed uploads, incremental processing, batched embeddings, and persistent metadata.

**Stack:** Python · FastAPI · SQLite · Qdrant · Sentence Transformers  
**Upload:** Resumable · offset-based · streamed to disk  
**Processing:** Background worker · streaming chunks · batched embeddings  
**Search:** 384-dimensional embeddings · cosine similarity  
**Validation:** 1 GiB upload with interruption/resume · 16 automated tests

---

## Table of Contents

- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Running the Service](#running-the-service)
- [API Documentation](#api-documentation)
  - [Endpoint Overview](#endpoint-overview)
  - [GET /health](#get-health)
  - [POST /uploads](#post-uploads)
  - [GET /uploads/{upload_id}](#get-uploadsupload_id)
  - [PATCH /uploads/{upload_id}](#patch-uploadsupload_id)
  - [POST /search](#post-search)
  - [Interrupted Upload / Resume](#interrupted-upload--resume)
- [Design Discussion](#design-discussion)
  - [1. Handling a 10 GB File on a 4 GB RAM Machine](#1-handling-a-10-gb-file-on-a-4-gb-ram-machine)
  - [2. Handling Interrupted Uploads](#2-handling-interrupted-uploads)
  - [3. Supporting Multiple Concurrent Uploads](#3-supporting-multiple-concurrent-uploads)
  - [4. Efficient Processing and Indexing](#4-efficient-processing-and-indexing)
  - [5. Semantic Search](#5-semantic-search)
  - [6. Supporting Thousands of Concurrent Uploads and Searches](#6-supporting-thousands-of-concurrent-uploads-and-searches)

---

# Architecture

```text
                              ┌──────────────────────┐
                              │       FastAPI        │
                              │         API          │
                              └──────────┬───────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
                    ▼                    ▼                    ▼
             Upload Management        SQLite              Semantic
                    │                 Metadata              Search
                    ▼                                        │
             Local File Storage                         Embedding Model
                    │                                        │
                    ▼                                        ▼
             Processing Job                              Qdrant
                    │                                  Vector Search
                    ▼
          ┌─────────────────────┐
          │  Background Worker  │
          └──────────┬──────────┘
                     │
              ┌──────┼───────┐
              ▼      ▼       ▼
           Chunking Embedding Indexing
```

### Components

| Component | Responsibility |
|---|---|
| **FastAPI** | REST API and request handling |
| **SQLite** | File, processing-job, and chunk metadata |
| **Local filesystem** | Persistent upload storage |
| **Background worker** | Asynchronous document processing |
| **Sentence Transformers** | Semantic embeddings |
| **Qdrant** | Vector storage and similarity search |

The local architecture intentionally uses lightweight infrastructure so the complete system can run on a developer machine. Production evolution is covered in the **Design Discussion** section.

---

# Project Structure

```text
large-file-search/
│
├── app/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── uploads.py
│   │   └── search.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── database.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── file.py
│   │   ├── job.py
│   │   └── chunk.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── upload_service.py
│   │   ├── processing_service.py
│   │   ├── chunking_service.py
│   │   ├── embedding_service.py
│   │   └── vector_store_service.py
│   │
│   ├── workers/
│   │   ├── __init__.py
│   │   └── processor.py
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   └── local.py
│   │
│   └── main.py
│
├── scripts/
│   └── upload.py
│
├── tests/
│   ├── test_chunking.py
│   ├── test_processor.py
│   ├── test_embedding_service.py
│   └── test_vector_store_service.py
│
├── data/
│   ├── uploads/
│   └── indexes/
│
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
└── README.md
```

---

# Setup

## Requirements

- Python 3.11+
- 4 GB RAM assignment environment
- Internet access on first startup to download the embedding model

## Install dependencies

Create and activate a virtual environment, then install the project dependencies:

```bash
python -m venv .venv
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\Activate.ps1
```

**Linux / macOS**

```bash
source .venv/bin/activate
```

Then:

```bash
pip install -r requirements.txt
```

Optional environment overrides can be provided using the variables shown in `.env.example`.

No separate database or vector-database installation is required for the default local setup.

---

# Running the Service

The API and background worker run as separate processes.

## Start the API

```bash
python -m uvicorn app.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Interactive API documentation is also available at:

```text
http://127.0.0.1:8000/docs
```

## Start the processing worker

Open a second terminal:

```bash
python -m app.workers.processor
```

The worker continuously checks for queued processing jobs and processes them asynchronously.

## Health Check

```text
GET /health
```

Response:

```json
{
  "status": "ok"
}
```

---

# API Documentation

The API uses JSON for metadata operations and streamed binary data for file chunks.

## Endpoint Overview

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Check service health |
| `POST` | `/uploads` | Create a resumable upload session |
| `GET` | `/uploads/{upload_id}` | Get upload status and current offset |
| `PATCH` | `/uploads/{upload_id}` | Upload the next binary chunk |
| `POST` | `/search` | Perform semantic search |

---

## GET /health

Checks whether the API process is running.

### Response

```json
{
  "status": "ok"
}
```

---

## POST /uploads

Creates a new resumable upload session.

The example below uses a **10 MiB file** and a **1 MiB upload chunk size**.

### Request

```json
{
  "filename": "document.txt",
  "size": 10485760
}
```

### Request Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `filename` | string | Yes | Original file name |
| `size` | integer | Yes | Total file size in bytes |

The requested size must not exceed the configured maximum file size of **10 GB**.

### Response

```json
{
  "upload_id": "5c8c5c7b-1234-4567-8901-123456789abc",
  "filename": "document.txt",
  "size": 10485760,
  "offset": 0,
  "status": "UPLOADING"
}
```

The returned `upload_id` identifies the upload session and is used for subsequent requests.

---

## GET /uploads/{upload_id}

Returns the current state of an upload.

This endpoint is used to determine where an interrupted upload should resume.

### Response

For example, after **5 MiB** has been persisted:

```json
{
  "upload_id": "5c8c5c7b-1234-4567-8901-123456789abc",
  "filename": "document.txt",
  "size": 10485760,
  "offset": 5242880,
  "status": "UPLOADING"
}
```

### Response Fields

| Field | Description |
|---|---|
| `upload_id` | Unique upload session identifier |
| `filename` | Original file name |
| `size` | Expected total file size |
| `offset` | Number of bytes already persisted |
| `status` | Current upload state |

The client can seek to the returned `offset` in the original file and continue uploading from that position.

---

## PATCH /uploads/{upload_id}

Uploads the next binary chunk.

In this example, the server has already persisted **5 MiB**, and the client is sending the next **1 MiB** chunk.

### Required Headers

```text
Content-Type: application/octet-stream
Content-Length: 1048576
Upload-Offset: 5242880
```

### Request Body

```text
<binary chunk>
```

### Header Description

| Header | Description |
|---|---|
| `Content-Type` | Identifies the request as binary data |
| `Content-Length` | Size of the current chunk in bytes |
| `Upload-Offset` | Byte offset at which this chunk is expected to start |

The server verifies that `Upload-Offset` matches the persisted offset before accepting the chunk.

The received byte count is also validated against `Content-Length`.

### Response

After successfully persisting the 1 MiB chunk:

```json
{
  "upload_id": "5c8c5c7b-1234-4567-8901-123456789abc",
  "filename": "document.txt",
  "size": 10485760,
  "offset": 6291456,
  "status": "UPLOADING"
}
```

The returned offset is now **6 MiB**.

When the final expected byte is received, the upload status becomes `COMPLETED`, the temporary `.part` file is atomically finalized, and a processing job is queued.

---

## POST /search

Performs semantic search across processed documents.

### Request

```json
{
  "query": "How does the system recover after a processing failure?",
  "limit": 5
}
```

### Request Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | Yes | Natural-language search query |
| `limit` | integer | No | Number of results; default `5`, maximum `20` |

### Response

```json
{
  "query": "How does the system recover after a processing failure?",
  "results": [
    {
      "file_id": "5c8c5c7b-1234-4567-8901-123456789abc",
      "filename": "document.txt",
      "chunk_id": "1f4c...",
      "chunk_index": 12,
      "score": 0.4032,
      "start_byte": 48210,
      "end_byte": 52140,
      "text": "..."
    }
  ]
}
```

### Result Fields

| Field | Description |
|---|---|
| `file_id` | Source file identifier |
| `filename` | Source file name |
| `chunk_id` | Unique chunk identifier |
| `chunk_index` | Position of the chunk in the document |
| `score` | Vector similarity score |
| `start_byte` | Starting byte position in the source file |
| `end_byte` | Ending byte position |
| `text` | Relevant source section |

Results are returned in vector-search ranking order and filtered using the configured similarity threshold.

---

## Interrupted Upload / Resume

The following example uses the same **10 MiB file with 1 MiB chunks**:

```text
1. POST /uploads
        │
        │ size = 10 MiB
        ▼
   offset = 0
        │
        ▼
2. PATCH /uploads/{id}
   1 MiB chunk
        │
        ▼
   offset = 1 MiB
        │
        ▼
   ... continue uploading ...
        │
        ▼
   offset = 5 MiB
        │
        X  ← connection interrupted
        │
        ▼
3. GET /uploads/{id}
        │
        ▼
   server reports offset = 5 MiB
        │
        ▼
4. Resume PATCH requests
   starting at byte 5 MiB
        │
        ▼
   offset = 10 MiB
        │
        ▼
   Upload COMPLETED
```

The server-side offset is the source of truth.

The client seeks to the returned offset in the original file and continues uploading from that position.

Clients should re-check the server's persisted offset after an ambiguous network failure before retrying, so already-persisted data is not blindly resent.

---

# Design Discussion

## 1. Handling a 10 GB File on a 4 GB RAM Machine

The key design principle is:

> **Memory usage should depend on the processing window, not the total file size.**

```text
                         10 GB FILE
                             │
                             ▼
                  ┌────────────────────┐
                  │ Streaming Upload   │
                  └─────────┬──────────┘
                            │
                       Small chunks
                            │
                            ▼
                  ┌────────────────────┐
                  │ Persistent Storage │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │ Background Worker  │
                  └─────────┬──────────┘
                            │
                   Stream incrementally
                            │
                            ▼
                  ┌────────────────────┐
                  │ Text Chunk         │
                  │ + Overlap          │
                  └─────────┬──────────┘
                            │
                     Batch embeddings
                            │
                            ▼
                         Qdrant
```

The entire 10 GB file is never loaded into RAM.

During upload, request data is streamed to disk.

During processing, the worker reads the file incrementally and processes bounded batches of chunks.

Current processing configuration:

```text
Chunk size:       ~4000 characters
Overlap:           ~500 characters
Embedding batch:   100 chunks
```

This keeps the normal processing window independent of the total file size.

A pathological single line can still temporarily exceed the intended chunk size, which is a known limitation of the current line-oriented chunker.

---

## 2. Handling Interrupted Uploads

Each upload maintains a persisted byte offset.

```text
Upload starts
     │
     ▼
 offset = 0
     │
     ▼
 Upload chunk
     │
     ▼
 offset = 8 MiB
     │
     ▼
 Upload chunk
     │
     ▼
 offset = 16 MiB
     │
     X  ← connection lost
     │
     ▼
GET /uploads/{id}
     │
     ▼
 offset = 16 MiB
     │
     ▼
Resume from byte 16 MiB
```

The client does not have to guess where the server stopped.

The persisted offset is the source of truth.

The server validates the incoming `Upload-Offset` before accepting the next chunk.

For an ambiguous network failure, the client should re-check the server offset before retrying.

The upload implementation also writes incoming data to a temporary `.part` file and atomically renames it when the expected file size has been reached. This avoids exposing an incomplete file as the finalized upload.

---

## 3. Supporting Multiple Concurrent Uploads

Uploads are isolated by upload ID.

```text
                    FastAPI
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      Upload A      Upload B      Upload C
          │            │            │
          ▼            ▼            ▼
       A.part        B.part        C.part
          │            │            │
          ▼            ▼            ▼
        Job A          Job B         Job C
```

A lock is scoped to an individual upload rather than globally across the application.

Therefore, concurrent requests for different uploads can progress independently.

For a multi-instance production deployment, shared object storage and distributed coordination would replace the local filesystem and in-process locking.

The current `.part.chunk` temporary file is also scoped to an upload. The local implementation is protected by the per-upload lock; a multi-instance deployment should use unique temporary object keys or storage-native multipart uploads.

---

## 4. Efficient Processing and Indexing

Large documents are processed as a streaming pipeline.

```text
                 Uploaded File
                      │
                      ▼
               Streaming Read
                      │
                      ▼
              ┌───────────────┐
              │    Chunking   │
              │  ~4000 chars  │
              │  ~500 overlap │
              └───────┬───────┘
                      │
                      ▼
              Embedding Batch
                  × 100
                      │
                ┌─────┴─────┐
                ▼           ▼
             SQLite       Qdrant
             Metadata     Vectors
```

### Chunking

Chunks are approximately 4000 characters with 500 characters of overlap.

The overlap preserves context across chunk boundaries.

### Embedding

Chunks are embedded in batches of 100 rather than individually.

This reduces per-item overhead while keeping memory usage controlled.

### Indexing

Each chunk's metadata is persisted in SQLite and its embedding is upserted into Qdrant.

Chunk identifiers are deterministic based on the file and chunk index. This allows processing retries to safely reinsert metadata and upsert the same vector rather than creating duplicates.

Processing jobs also record progress, allowing the service to expose processed bytes and chunk counts.

---

## 5. Semantic Search

The service uses:

```text
sentence-transformers/all-MiniLM-L6-v2
```

to convert text into **384-dimensional embeddings**.

### Indexing

```text
Document
   │
   ▼
Text chunks
   │
   ▼
Embedding Model
   │
   ▼
384-dimensional vectors
   │
   ▼
Qdrant
```

### Query

```text
Natural-language query
          │
          ▼
    Embedding Model
          │
          ▼
     Query Vector
          │
          ▼
 Qdrant Cosine Similarity
          │
          ▼
    Top-K Chunk IDs
          │
          ▼
       SQLite
          │
          ▼
Source Text + Metadata
```

The search is based on semantic similarity rather than exact keyword matching.

For example:

```text
"How does the system recover after a processing failure?"
```

can retrieve content discussing worker retries or failed jobs even when the exact wording does not appear in the source document.

The vector search returns candidate chunks, after which the application retrieves the corresponding source text and metadata from SQLite.

A similarity threshold of `0.30` is currently applied before results are returned.

---

## 6. Supporting Thousands of Concurrent Uploads and Searches

The current implementation is intentionally local:

```text
                         LOCAL
────────────────────────────────────────

                       FastAPI
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
           SQLite        Disk       Qdrant
                          │
                          ▼
                       Worker
```

For thousands of concurrent uploads and searches, the architecture would evolve to:

```text
                         Load Balancer
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
             API #1          API #2          API #N
                │              │              │
                └──────────────┼──────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        Object Storage     PostgreSQL      Durable Queue
                                                  │
                                  ┌───────────────┼───────────────┐
                                  ▼               ▼               ▼
                               Worker #1       Worker #2       Worker #N
                                  │               │               │
                                  └───────────────┼───────────────┘
                                                  │
                                                  ▼
                                         Distributed Qdrant
```

### Scaling Strategy

| Concern | Local Implementation | Production Approach |
|---|---|---|
| File storage | Local filesystem | Object storage |
| Metadata | SQLite | PostgreSQL |
| Processing jobs | SQLite polling | Durable queue |
| Workers | Single worker | Horizontally scaled workers |
| API | Single instance | Load-balanced instances |
| Vector search | Local Qdrant | Distributed Qdrant |
| Concurrency control | In-process lock | Distributed coordination |

### Upload Scaling

Large uploads should go directly to object storage using multipart/resumable upload mechanisms where possible.

This prevents API servers from becoming the bottleneck for multi-gigabyte transfers.

### Processing Scaling

Workers can scale independently based on queue depth.

```text
                 Queue
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
      Worker 1  Worker 2   Worker N
        │          │          │
        └──────────┼──────────┘
                   │
                   ▼
              Qdrant Index
```

This separates upload traffic from CPU-intensive embedding work.

### Search Scaling

Search traffic should scale independently from document processing.

The vector database can be distributed according to:

- vector count
- query rate
- latency requirements
- available memory

### Resource Protection

At high concurrency, the production system should also introduce:

- per-user upload quotas
- rate limiting
- concurrent-upload limits
- worker concurrency limits
- queue backpressure
- request timeouts
- metrics and tracing
- monitoring and alerting

The central scaling principle is to **separate upload traffic, document processing, and search traffic** so that a spike in one workload does not exhaust resources required by the others.
