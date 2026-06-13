"""Recipe agent domain package.

Groups the recipe agent's construction entry point, its typed domain models, and
its ``ingestion`` layer (origin-specific adapters that materialize recipes into
the knowledge base) under one package. At query time the agent uses dedicated
``search_recipes`` and ``get_recipe_detail`` tools instead of Agno's native
knowledge search.
"""
