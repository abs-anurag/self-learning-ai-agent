/**
 * Zustand store for Self Search state.
 *
 * In-memory browser session management for:
 * - Document text (not persisted to disk or database)
 * - Current question input
 * - Latest answer and supporting passage citations
 * - Session Q&A history
 * - Loading and error states
 */

import { create } from 'zustand';
import { askSelfSearch } from '../api/selfSearchApi.js';

export const useSelfSearchStore = create((set, get) => ({
  document: '',
  question: '',
  answer: null,
  loading: false,
  error: null,
  history: [],

  setDocument: (document) => set({ document, error: null }),

  setQuestion: (question) => set({ question, error: null }),

  clearDocument: () =>
    set({
      document: '',
      question: '',
      answer: null,
      error: null,
    }),

  clearHistory: () => set({ history: [] }),

  clearError: () => set({ error: null }),

  askQuestion: async (questionOverride) => {
    const { document, question, history } = get();
    const activeQuestion = (questionOverride ?? question).trim();
    const activeDoc = document.trim();

    if (!activeDoc) {
      set({
        error: {
          code: 'VALIDATION_ERROR',
          message: 'Please provide document text before asking a question.',
        },
      });
      return null;
    }

    if (!activeQuestion) {
      set({
        error: {
          code: 'VALIDATION_ERROR',
          message: 'Please enter a question to search the document.',
        },
      });
      return null;
    }

    set({ loading: true, error: null });

    try {
      const response = await askSelfSearch(activeDoc, activeQuestion);

      const historyEntry = {
        id: `qa_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`,
        timestamp: new Date().toISOString(),
        question: activeQuestion,
        response,
      };

      set({
        answer: response,
        question: '',
        loading: false,
        history: [historyEntry, ...history],
      });

      return response;
    } catch (err) {
      const formattedError = {
        code: err?.code ?? 'SELF_SEARCH_ERROR',
        message: err?.message ?? 'Failed to execute Self Search request.',
        status: err?.status ?? 500,
      };

      set({
        error: formattedError,
        loading: false,
      });

      return null;
    }
  },
}));

export default useSelfSearchStore;
