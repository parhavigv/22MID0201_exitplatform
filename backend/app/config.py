from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment configuration. Read once, cached for the process lifetime."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Supabase ---------------------------------------------------------
    supabase_url: str = ""
    """e.g. https://abcdefgh.supabase.co"""

    supabase_anon_key: str = ""
    """Public by design. Requests made with it are subject to RLS."""

    supabase_service_key: str = ""
    """Bypasses RLS. Only the executor, the sweep job, and audit writes may use
    it — never a request handler acting on behalf of a user, and never an agent
    tool. See CLAUDE.md rule 1."""

    supabase_jwt_secret: str = ""
    """Legacy HS256 signing secret. Leave empty on projects using asymmetric
    JWT signing keys — the JWKS endpoint is used instead."""

    database_url: str = ""
    """Direct Postgres (session pooler). Used by scripts/apply_migrations.py
    and by the LangGraph PostgresSaver checkpointer (agent/graph.py)."""

    # --- LLM ----------------------------------------------------------------
    # Two shapes are supported: calling Anthropic directly (ANTHROPIC_*), or
    # routing through the Portkey gateway this deployment actually uses
    # (PORTKEY_*, self-hosted -> Vertex -> Claude). Whichever is present wins;
    # PORTKEY_* takes priority because that's what backend/.env has filled in.
    # See backend/scripts/discover_gateway.py and probe_gateway.py for how
    # this was established, and CLAUDE.md's "Model call shape" for the target
    # call — llm.py degrades gracefully where the gateway falls short of it.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    anthropic_base_url: str = ""
    """Set only when routing through a gateway via the ANTHROPIC_* names.
    Empty means call Anthropic directly."""

    portkey_api_key: str = ""
    portkey_base_url: str = ""
    portkey_model: str = ""
    """The gateway's own model slug, e.g. '@dsvertex/anthropic.claude-opus-5'.
    Not necessarily an allowed slug — that's an allow-list on the gateway's
    side, verify with probe_gateway.py before assuming a new value works."""

    @property
    def llm_base_url(self) -> str:
        raw = self.portkey_base_url or self.anthropic_base_url
        # The anthropic SDK appends /v1/messages itself; a base_url already
        # ending in /v1 produces /v1/v1/messages and a 404 (discover_gateway.py).
        return raw.rstrip("/").removesuffix("/v1")

    @property
    def llm_model(self) -> str:
        return self.portkey_model or self.anthropic_model

    @property
    def llm_default_headers(self) -> dict[str, str]:
        """Gateway auth is x-portkey-api-key — the gateway rejects Anthropic's
        native x-api-key with a 401 (probe_gateway.py established this)."""
        if self.portkey_api_key:
            return {"x-portkey-api-key": self.portkey_api_key}
        return {}

    @property
    def llm_api_key(self) -> str:
        """Only meaningful for a direct-Anthropic deployment — the gateway
        path ignores this and authenticates via llm_default_headers instead."""
        return self.anthropic_api_key or "unused"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and (self.portkey_api_key or self.anthropic_api_key))

    # --- Embeddings (Phase 5 RAG) -----------------------------------------
    # Same Portkey gateway as the LLM — auth via portkey_api_key.
    # text-embedding-3-small supports `dimensions=1024`, matching vector(1024).
    embedding_model: str = "@azure-openai-eus2/text-embedding-3-small"
    embedding_dimensions: int = 1024

    # --- Sweep scheduler (Phase 7) ----------------------------------------
    sweep_enabled: bool = True
    """Set to False to disable the nightly sweep (useful in test envs)."""
    sweep_hour: int = 2
    sweep_minute: int = 0
    """Local server time when the nightly sweep fires. Default 02:00."""

    # --- App --------------------------------------------------------------
    cors_origins: str = "http://localhost:5173"
    environment: str = "development"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def configured(self) -> bool:
        """False until a Supabase project exists. Lets the app boot and serve
        /health so the skeleton is runnable before Phase 0 finishes."""
        return bool(self.supabase_url and self.supabase_anon_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
