"""Recipe agent domain package.

Groups the recipe agent's construction entry point, its typed domain models, and
its ``ingestion`` layer (origin-specific adapters that materialize recipes into
the knowledge base) under one package. The agent reads recipes back through
Agno's native knowledge search, so there is no separate query layer.
"""
