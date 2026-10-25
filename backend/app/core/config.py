from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017/?replicaSet=rs0"
    mongodb_db: str = "teammind"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 720

    llm_provider: str = "gemini"  # gemini | fake
    llm_api_key: str = ""
    llm_model_main: str = "gemini-2.5-flash"
    llm_model_fast: str = "gemini-2.5-flash-lite"
    llm_thinking_budget: int = 0

    embedding_backend: str = "local"  # local | hash
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dims: int = 384

    worthiness_threshold: float = 0.6
    similarity_threshold: float = 0.45
    min_semantic: float = 0.25
    rerank_enabled: bool = False
    stale_days: int = 14
    decay_half_life_days: float = 60
    archive_threshold: float = 0.12
    reflection_min_group: int = 3
    rate_limit_per_min: int = 30
    cors_origins: str = "http://localhost:5173"

    # ---- LangGraph ----
    use_langgraph: bool = True            # false = old plain-function pipeline (agents/orchestrator.py)
    graph_checkpointer: str = "mongo"     # mongo (MongoDBSaver) | memory (tests / no database)
    graph_recursion_limit: int = 100      # loops need more than LangGraph's default of 25
    learn_max_candidates: int = 5         # max memories the Learn graph handles per chat turn
    judge_confidence_min: float = 0.6     # below this the Learn graph pauses and asks a human
    thread_retention_days: float = 7      # purge_threads: finished graph threads older than this are deleted
    reflection_require_approval: bool = False
    demo_ask_on_conflict: bool = False    # demo helper: always ask the human when the judge says "contradicts"

    # ranking weights (sum = 1)
    w_semantic: float = 0.55
    w_keyword: float = 0.15
    w_recency: float = 0.15
    w_importance: float = 0.15


settings = Settings()
