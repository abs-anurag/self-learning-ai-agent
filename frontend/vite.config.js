import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
	plugins: [react()],
	server: {
		port: 5173,
		proxy: {
			'/tasks': {
				target: 'http://localhost:8000',
				changeOrigin: true,
			},
			'/memory': {
				target: 'http://localhost:8000',
				changeOrigin: true,
			},
			'/metrics': {
				target: 'http://localhost:8000',
				changeOrigin: true,
			},
			'/health': {
				target: 'http://localhost:8000',
				changeOrigin: true,
			},
			'/ws': {
				target: 'ws://localhost:8000',
				ws: true,
				changeOrigin: true,
			},
		},
	},
})
