"""Shape / typing tests for the ``Recipe`` domain model.

Construct the model and assert the structured ``ingredients`` shape and the
``IngredientRole`` enum. ``quantity`` is a raw string (ranges survive),
``difficulty`` is a 1-5 int, and ingredients carry an ``optional`` flag. No
parsing, network, DB, or LLM is exercised.
"""

from __future__ import annotations

from spectres_runtime.recipe_agent.models import (
    Ingredient,
    IngredientRole,
    Recipe,
    RecipeProvenance,
)


def test_role_enum_values() -> None:
    assert {r.value for r in IngredientRole} == {"main", "supporting", "seasoning"}


def test_ingredient_defaults_and_shape() -> None:
    ingredient = Ingredient(name="garlic")
    assert ingredient.name == "garlic"
    assert ingredient.quantity is None
    assert ingredient.unit is None
    assert ingredient.role is IngredientRole.MAIN
    assert ingredient.optional is False


def test_ingredient_full_shape_with_range_quantity() -> None:
    ingredient = Ingredient(
        name="cooking oil",
        quantity="10-15",
        unit="ml",
        role=IngredientRole.SEASONING,
        optional=True,
    )
    assert ingredient.quantity == "10-15"
    assert ingredient.unit == "ml"
    assert ingredient.role is IngredientRole.SEASONING
    assert ingredient.optional is True


def test_recipe_minimal_construction() -> None:
    recipe = Recipe(id="r1", name="Tomato Eggs")
    assert recipe.id == "r1"
    assert recipe.name == "Tomato Eggs"
    assert recipe.aliases == []
    assert recipe.description is None
    assert recipe.images == []
    assert recipe.ingredients == []
    assert recipe.steps is None
    assert recipe.servings is None
    assert recipe.difficulty is None
    assert recipe.provenance is None


def test_recipe_structured_ingredients() -> None:
    recipe = Recipe(
        id="r2",
        name="Braised Pork",
        description="A homestyle braised pork belly.",
        images=["recipes/r2/cover.jpg", "recipes/r2/plated.jpg"],
        ingredients=[
            Ingredient(name="pork belly", quantity="500", unit="g"),
            Ingredient(name="sugar", quantity="20", unit="g", role=IngredientRole.SEASONING),
        ],
        steps="### Prep\n\n1. Blanch the pork.\n2. Caramelize the sugar.",
        servings=4,
        difficulty=3,
        time=1.5,
        provenance=RecipeProvenance(source="howtocook", ref="dishes/meat_dish/..."),
    )
    assert [i.name for i in recipe.ingredients] == ["pork belly", "sugar"]
    assert recipe.images == ["recipes/r2/cover.jpg", "recipes/r2/plated.jpg"]
    assert recipe.ingredients[1].role is IngredientRole.SEASONING
    assert recipe.steps is not None
    assert recipe.steps.startswith("### Prep")
    assert recipe.servings == 4
    assert recipe.difficulty == 3
    assert recipe.time == 1.5
    assert recipe.provenance is not None
    assert recipe.provenance.source == "howtocook"
