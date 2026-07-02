"""
Cookidoo MCP Server
Main server file containing MCP tool definitions for interacting with Cookidoo.

Angepasst für Railway-Deployment: Streamable HTTP Transport statt stdio,
Port aus Umgebungsvariable PORT (wird von Railway gesetzt).
"""

import os
import json

from fastmcp import FastMCP
from cookidoo_service import CookidooService, load_cookidoo_credentials
from schemas import CustomRecipe

# Initialize FastMCP server
mcp = FastMCP("cookidoo-mcp-server")

# Module-level state to store the authenticated session
_cookidoo_service: CookidooService | None = None
_cookidoo_api = None


async def _ensure_connected() -> str | None:
    """
    Stellt sicher, dass eine Cookidoo-Session existiert.
    Verbindet automatisch, falls noch keine Session vorhanden ist.
    Gibt None zurück bei Erfolg, sonst eine Fehlermeldung.
    """
    global _cookidoo_service, _cookidoo_api

    if _cookidoo_api:
        return None

    try:
        email, password = load_cookidoo_credentials()
        _cookidoo_service = CookidooService(email, password)
        _cookidoo_api = await _cookidoo_service.login()
        return None
    except ValueError as e:
        return (
            f"Configuration Error: {str(e)}\n\n"
            "Bitte COOKIDOO_EMAIL und COOKIDOO_PASSWORD als "
            "Umgebungsvariablen in Railway setzen."
        )
    except Exception as e:
        return f"Connection Failed: {str(e)}"


@mcp.tool()
async def connect_to_cookidoo() -> str:
    """
    Authenticate with Cookidoo and store the session.

    This tool must be called before using other Cookidoo tools. It will:
    1. Load your Cookidoo credentials from environment variables
    2. Authenticate with the Cookidoo platform
    3. Store the authenticated session for use by other tools

    Returns:
        str: Success message confirming connection
    """
    global _cookidoo_api

    error = await _ensure_connected()
    if error:
        return error

    email, _ = load_cookidoo_credentials()
    return f"Successfully connected to Cookidoo as {email}"


@mcp.tool()
async def get_recipe_details(recipe_id: str) -> str:
    """
    Get detailed information about a specific recipe by its ID.

    Use this tool to get full details about a recipe for inspiration before
    creating your own custom recipe.

    Args:
        recipe_id: The Cookidoo recipe ID (e.g., "r59322", "r907015")

    Returns:
        str: Detailed recipe information including ingredients, steps,
             cooking time, etc.
    """
    global _cookidoo_api

    error = await _ensure_connected()
    if error:
        return error

    try:
        recipe = await _cookidoo_api.get_recipe_details(recipe_id)

        result = "Recipe Details:\n\n"
        result += f"Name: {recipe.name}\n"
        result += f"ID: {recipe.id}\n\n"

        if hasattr(recipe, 'serving_size'):
            result += f"Servings: {recipe.serving_size}\n"
        if hasattr(recipe, 'total_time'):
            result += f"Total Time: {recipe.total_time} minutes\n"
        if hasattr(recipe, 'difficulty'):
            result += f"Difficulty: {recipe.difficulty}\n"
        result += "\n"

        if hasattr(recipe, 'ingredients') and recipe.ingredients:
            result += "Ingredients:\n"
            for ingredient in recipe.ingredients:
                if hasattr(ingredient, 'name'):
                    result += f"  • {ingredient.name}"
                    if hasattr(ingredient, 'quantity') and ingredient.quantity:
                        result += f" - {ingredient.quantity}"
                    result += "\n"
            result += "\n"

        if hasattr(recipe, 'steps') and recipe.steps:
            result += "Steps:\n"
            for i, step in enumerate(recipe.steps, 1):
                if hasattr(step, 'description'):
                    result += f"{i}. {step.description}\n"
            result += "\n"

        if hasattr(recipe, 'url') and recipe.url:
            result += f"URL: {recipe.url}\n"

        return result

    except Exception as e:
        return f"Failed to get recipe details: {str(e)}"


@mcp.tool()
async def generate_recipe_structure(
    name: str,
    ingredients: str,
    steps: str,
    servings: int = 4,
    prep_time: int = 30,
    total_time: int = 60,
    hints: str = "",
) -> str:
    """
    Generate and validate a recipe structure ready for upload to Cookidoo.

    This tool helps you structure your recipe data properly before uploading.
    It validates all fields and returns a JSON structure that can be used with
    the upload_custom_recipe tool.

    Args:
        name: Recipe name (required)
        ingredients: Ingredients list, one per line or comma-separated
        steps: Cooking steps, one per line or numbered
        servings: Number of servings (default: 4, range: 1-20)
        prep_time: Preparation time in minutes (default: 30)
        total_time: Total cooking time in minutes (default: 60)
        hints: Optional cooking tips, one per line or comma-separated

    Returns:
        str: Validated recipe structure in JSON format, ready for upload
    """
    try:
        ingredients_list = [
            ing.strip()
            for ing in (ingredients.split('\n') if '\n' in ingredients else ingredients.split(','))
            if ing.strip()
        ]

        steps_list = [
            step.strip().lstrip('0123456789.)-• ')
            for step in steps.split('\n')
            if step.strip()
        ]

        hints_list = None
        if hints:
            hints_list = [
                hint.strip()
                for hint in (hints.split('\n') if '\n' in hints else hints.split(','))
                if hint.strip()
            ]

        recipe = CustomRecipe(
            name=name,
            ingredients=ingredients_list,
            steps=steps_list,
            servings=servings,
            prep_time=prep_time,
            total_time=total_time,
            hints=hints_list
        )

        recipe_json = recipe.model_dump_json(indent=2)
        return (
            "Recipe structure validated successfully!\n\n"
            f"{recipe_json}\n\n"
            "You can now use this with 'upload_custom_recipe'."
        )

    except Exception as e:
        return f"Validation failed: {str(e)}\n\nPlease check your recipe data and try again."


@mcp.tool()
async def upload_custom_recipe(recipe_json: str) -> str:
    """
    Upload a custom recipe to your Cookidoo account.

    This tool creates a brand new recipe from scratch on your Cookidoo account.
    Use 'generate_recipe_structure' first to validate your recipe data, then
    pass the resulting JSON to this tool.

    Args:
        recipe_json: The validated recipe JSON from generate_recipe_structure

    Returns:
        str: Success message with the created recipe ID
    """
    global _cookidoo_service, _cookidoo_api

    error = await _ensure_connected()
    if error:
        return error

    try:
        try:
            recipe_data = json.loads(recipe_json)
            recipe = CustomRecipe(**recipe_data)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {str(e)}"
        except Exception as e:
            return f"Invalid recipe data: {str(e)}"

        recipe_id = await _cookidoo_service.create_custom_recipe(
            name=recipe.name,
            ingredients=recipe.ingredients,
            steps=recipe.steps,
            servings=recipe.servings,
            prep_time=recipe.prep_time,
            total_time=recipe.total_time,
            hints=recipe.hints
        )

        localization = _cookidoo_api.localization
        recipe_url = f"https://{localization.url}/recipes/custom-recipes/{recipe_id}"

        return (
            f"Recipe '{recipe.name}' created successfully!\n\n"
            f"Recipe ID: {recipe_id}\n"
            f"URL: {recipe_url}\n\n"
            "Your recipe is now saved in your Cookidoo account!"
        )

    except Exception as e:
        return f"Upload failed: {str(e)}"


if __name__ == "__main__":
    # Railway setzt die PORT-Umgebungsvariable automatisch.
    # Streamable HTTP ist der Transport, den Claude.ai Custom Connectors erwarten.
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="http", host="0.0.0.0", port=port)
