llm-openui/
│
├── main.py                     # FastAPI bootstrap (only app init)
├── config.py                  # env + constants
├── dependencies.py            # shared deps (db, redis, minio clients)
│
├── routers/                   # API layer (VERY IMPORTANT)
│   ├── chat.py                # /chat endpoints
│   ├── upload.py             # /upload endpoints
│   ├── files.py              # file management APIs
│   └── health.py             # health checks
│
├── services/                  # business logic layer
│   ├── rag_service.py        # core ask() logic
│   ├── ingest_service.py     # ingestion pipeline
│   ├── llm_service.py        # ollama calls
│   ├── embed_service.py      # embedding logic
│
├── retrieval/                 # RAG engine (core intelligence)
│   ├── chunking.py           # chunk logic
│   ├── search.py             # vector search
│   ├── rerank.py             # optional reranking
│   └── pipeline.py           # retrieval orchestration
│
├── database/                  # persistence layer
│   ├── db.py                 # postgres + pgvector queries
│   ├── models.py             # schema definitions (optional SQLAlchemy)
│   └── redis.py              # caching layer
│
├── storage/                   # object storage layer
│   ├── minio_client.py      # upload/download
│   └── file_store.py        # abstraction over minio
│
├── workers/                   # async background jobs (next upgrade)
│   ├── ingest_worker.py
│   └── queue.py
│
├── tools/                     # (future) agent tools
│   ├── web_search.py
│   ├── calculator.py
│   └── function_registry.py
│
├── utils/                     # helpers
│   ├── logger.py
│   ├── text.py
│   └── time.py
│
├── tests/
│   ├── test_chat.py
│   ├── test_ingest.py
│   └── test_retrieval.py
│
├── data/
│   └── uploads/
│
├── requirements.txt
└── README.md