/**
 * Self Search API client.
 *
 * Dispatches grounded document queries to POST /self-search/ask.
 * Reuses the central http.js client and authentication headers.
 */

import { post } from './http.js';

/**
 * Ask a natural-language question grounded in a user-provided document.
 *
 * @param {string} document - Source text document (1 to 100,000 characters)
 * @param {string} question - Question to answer based on the document (1 to 2,000 characters)
 * @returns {Promise<{
 *   answer: string,
 *   source_passages: Array<{
 *     text: string,
 *     relevance: 'direct'|'inferred'|'partial',
 *     verified: boolean,
 *     start_offset?: number,
 *     end_offset?: number
 *   }>,
 *   confidence: 'high'|'medium'|'low'|'unsupported',
 *   is_supported: boolean,
 *   explanation?: string|null
 * }>}
 */
export async function askSelfSearch(document, question) {
  return post('/self-search/ask', { document, question });
}

export default {
  askSelfSearch,
};
