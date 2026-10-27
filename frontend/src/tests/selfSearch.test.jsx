import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the API layer before importing page and store
vi.mock('../api/selfSearchApi.js', () => ({
	askSelfSearch: vi.fn(),
	default: {
		askSelfSearch: vi.fn(),
	},
}))

import { askSelfSearch } from '../api/selfSearchApi.js'
import SelfSearchPage from '../pages/SelfSearchPage.jsx'
import { useSelfSearchStore } from '../store/selfSearchStore.js'

describe('Self Search Feature (Frontend)', () => {
	beforeEach(() => {
		vi.clearAllMocks()
		useSelfSearchStore.getState().clearDocument()
		useSelfSearchStore.getState().clearHistory()
		useSelfSearchStore.getState().clearError()
	})

	describe('useSelfSearchStore', () => {
		it('manages document and question state correctly', () => {
			const store = useSelfSearchStore.getState()
			expect(store.document).toBe('')
			expect(store.question).toBe('')
			expect(store.answer).toBeNull()

			act(() => {
				store.setDocument('PostgreSQL is a relational database.')
				store.setQuestion('What is PostgreSQL?')
			})

			const updated = useSelfSearchStore.getState()
			expect(updated.document).toBe('PostgreSQL is a relational database.')
			expect(updated.question).toBe('What is PostgreSQL?')
		})

		it('validates against empty document input in askQuestion', async () => {
			const store = useSelfSearchStore.getState()
			act(() => {
				store.setDocument('   ')
				store.setQuestion('What is this?')
			})

			let result
			await act(async () => {
				result = await store.askQuestion()
			})

			expect(result).toBeNull()
			expect(askSelfSearch).not.toHaveBeenCalled()
			expect(useSelfSearchStore.getState().error?.code).toBe('VALIDATION_ERROR')
		})

		it('validates against empty question input in askQuestion', async () => {
			const store = useSelfSearchStore.getState()
			act(() => {
				store.setDocument('PostgreSQL is a database.')
				store.setQuestion('   ')
			})

			let result
			await act(async () => {
				result = await store.askQuestion()
			})

			expect(result).toBeNull()
			expect(askSelfSearch).not.toHaveBeenCalled()
			expect(useSelfSearchStore.getState().error?.code).toBe('VALIDATION_ERROR')
		})

		it('successfully queries API and records session history', async () => {
			const mockResponse = {
				answer: 'Cats bark loudly at night.',
				source_passages: [
					{
						text: 'Cats bark loudly at night.',
						relevance: 'direct',
						verified: true,
						start_offset: 0,
						end_offset: 26,
					},
				],
				confidence: 'high',
				is_supported: true,
				explanation: null,
			}
			askSelfSearch.mockResolvedValueOnce(mockResponse)

			const store = useSelfSearchStore.getState()
			act(() => {
				store.setDocument('Cats bark loudly at night. Dogs can fly in the sky.')
				store.setQuestion('How do cats sound?')
			})

			let res
			await act(async () => {
				res = await store.askQuestion()
			})

			expect(res).toEqual(mockResponse)
			expect(askSelfSearch).toHaveBeenCalledWith(
				'Cats bark loudly at night. Dogs can fly in the sky.',
				'How do cats sound?',
			)

			const state = useSelfSearchStore.getState()
			expect(state.answer).toEqual(mockResponse)
			expect(state.history).toHaveLength(1)
			expect(state.history[0].question).toBe('How do cats sound?')
			expect(state.history[0].response).toEqual(mockResponse)
		})

		it('handles API failure and sets formatted error state', async () => {
			askSelfSearch.mockRejectedValueOnce({
				status: 502,
				code: 'LLM_PROVIDER_ERROR',
				message: 'Provider timeout',
			})

			const store = useSelfSearchStore.getState()
			act(() => {
				store.setDocument('Sample document text.')
				store.setQuestion('Sample question?')
			})

			let res
			await act(async () => {
				res = await store.askQuestion()
			})

			expect(res).toBeNull()
			const state = useSelfSearchStore.getState()
			expect(state.error?.code).toBe('LLM_PROVIDER_ERROR')
			expect(state.error?.message).toBe('Provider timeout')
			expect(state.loading).toBe(false)
		})
	})

	describe('SelfSearchPage UI Component', () => {
		it('renders header, memory notice, and inputs', () => {
			render(<SelfSearchPage />)

			expect(screen.getByRole('heading', { level: 1, name: /Self Search/i })).toBeInTheDocument()
			expect(screen.getByText(/Direct In-Memory Session:/i)).toBeInTheDocument()
			expect(screen.getByLabelText(/Document text/i)).toBeInTheDocument()
			expect(screen.getByLabelText(/Ask a question/i)).toBeInTheDocument()
			expect(screen.getByRole('button', { name: /Search/i })).toBeDisabled()
		})

		it('updates document text and enables search button when both inputs have content', () => {
			render(<SelfSearchPage />)

			const docInput = screen.getByLabelText(/Document text/i)
			const qInput = screen.getByLabelText(/Ask a question/i)
			const searchBtn = screen.getByRole('button', { name: /Search/i })

			fireEvent.change(docInput, { target: { value: 'Birds live in trees.' } })
			expect(searchBtn).toBeDisabled() // Question still empty

			fireEvent.change(qInput, { target: { value: 'Where do birds live?' } })
			expect(searchBtn).not.toBeDisabled()
		})

		it('clears document when Clear document button is clicked', () => {
			render(<SelfSearchPage />)

			const docInput = screen.getByLabelText(/Document text/i)
			fireEvent.change(docInput, { target: { value: 'Some text to clear.' } })

			const clearBtn = screen.getByRole('button', { name: /Clear document/i })
			expect(clearBtn).toBeInTheDocument()

			fireEvent.click(clearBtn)
			expect(screen.getByLabelText(/Document text/i).value).toBe('')
		})

		it('submits query and renders supported answer with verified citation card', async () => {
			const mockAnswer = {
				answer: 'Birds live in trees.',
				source_passages: [
					{
						text: 'Birds live in trees.',
						relevance: 'direct',
						verified: true,
						start_offset: 0,
						end_offset: 20,
					},
				],
				confidence: 'high',
				is_supported: true,
				explanation: null,
			}
			askSelfSearch.mockResolvedValueOnce(mockAnswer)

			render(<SelfSearchPage />)

			fireEvent.change(screen.getByLabelText(/Document text/i), {
				target: { value: 'Birds live in trees.' },
			})
			fireEvent.change(screen.getByLabelText(/Ask a question/i), {
				target: { value: 'Where do birds live?' },
			})

			fireEvent.click(screen.getByRole('button', { name: /Search/i }))

			await waitFor(() => {
				expect(screen.getByText('Birds live in trees.')).toBeInTheDocument()
			})

			expect(screen.getByText(/VERIFIED CITATION/i)).toBeInTheDocument()
			expect(screen.getByText(/Confidence: high/i)).toBeInTheDocument()
		})

		it('renders unsupported warning when information is not in document', async () => {
			const mockUnsupported = {
				answer: 'The provided document does not contain sufficient information.',
				source_passages: [],
				confidence: 'unsupported',
				is_supported: false,
				explanation: 'No relevant facts found.',
			}
			askSelfSearch.mockResolvedValueOnce(mockUnsupported)

			render(<SelfSearchPage />)

			fireEvent.change(screen.getByLabelText(/Document text/i), {
				target: { value: 'Cats bark loudly.' },
			})
			fireEvent.change(screen.getByLabelText(/Ask a question/i), {
				target: { value: 'Can birds fly?' },
			})

			fireEvent.click(screen.getByRole('button', { name: /Search/i }))

			await waitFor(() => {
				expect(screen.getByText(/Information Not Available in Document/i)).toBeInTheDocument()
			})

			expect(
				screen.getByText(/The provided document does not contain sufficient verified evidence/i),
			).toBeInTheDocument()
		})
	})
})
