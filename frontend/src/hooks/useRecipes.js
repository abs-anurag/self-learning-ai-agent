/**
 * useRecipes — fetch and navigate the paginated trusted recipe list.
 *
 * Source of truth: BLUEPRINT.md §15 GET /memory/recipes
 *
 * Exposes:
 *   recipes     — Array of RecipeItem objects
 *   loading     — true while fetching
 *   error       — Error details or null
 *   pagination  — { page, pageSize, total }
 *   fetchPage   — Fetch a specific page
 *   refresh     — Re-fetch the current page
 */

import { useEffect, useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useAgentStore } from '../store/agentStore.js';

/**
 * @param {object}  [options]
 * @param {number}  [options.page=1]
 * @param {number}  [options.pageSize=20]
 * @param {boolean} [options.autoFetch=true]
 */
export function useRecipes({ page = 1, pageSize = 20, autoFetch = true } = {}) {
  const { recipes, recipesLoading, recipesError, recipesPagination, fetchRecipes } = useAgentStore(
    useShallow((s) => ({
      recipes: s.recipes,
      recipesLoading: s.recipesLoading,
      recipesError: s.recipesError,
      recipesPagination: s.recipesPagination,
      fetchRecipes: s.fetchRecipes,
    }))
  );

  const fetchPage = useCallback(
    (p = 1, ps = pageSize) => fetchRecipes(p, ps),
    [fetchRecipes, pageSize]
  );

  const refresh = useCallback(() => {
    fetchRecipes(recipesPagination.page, recipesPagination.pageSize);
  }, [fetchRecipes, recipesPagination.page, recipesPagination.pageSize]);

  useEffect(() => {
    if (autoFetch) fetchRecipes(page, pageSize);
  }, [autoFetch, page, pageSize, fetchRecipes]);

  return {
    recipes,
    loading: recipesLoading,
    error: recipesError,
    pagination: recipesPagination,
    fetchPage,
    refresh,
  };
}

export default useRecipes;
