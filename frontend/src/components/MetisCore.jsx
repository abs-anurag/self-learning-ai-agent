import { Canvas, useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'

const STATE_MODE = {
  pending: 'idle',
  running: 'processing',
  succeeded: 'success',
  failed: 'error',
  planning: 'planning',
  evaluating: 'evaluating',
  learning: 'learning',
  tool_use: 'tool_use',
}

const MODE_STYLES = {
  idle: { glow: '#777777', accent: '#b8b8b8' },
  listening: { glow: '#c4c4c4', accent: '#f0f0f0' },
  processing: { glow: '#bdbdbd', accent: '#ededed' },
  planning: { glow: '#b0b0b0', accent: '#e5e5e5' },
  thinking: { glow: '#b8b8b8', accent: '#e8e8e8' },
  tool_use: { glow: '#a8a8a8', accent: '#dedede' },
  evaluating: { glow: '#b3b3b3', accent: '#e6e6e6' },
  learning: { glow: '#a1a1a1', accent: '#d8d8d8' },
  speaking: { glow: '#d0d0d0', accent: '#f4f4f4' },
  success: { glow: '#d8d8d8', accent: '#ffffff' },
  error: { glow: '#929292', accent: '#c5c5c5' },
}

const TAU = Math.PI * 2
const NODE_DIRECTIONS = Array.from({ length: 8 }, (_, index) => {
  const vertical = 1 - (2 * (index + 0.5)) / 8
  const planar = Math.sqrt(1 - vertical * vertical)
  const angle = index * Math.PI * (3 - Math.sqrt(5))
  return [Math.cos(angle) * planar, vertical, Math.sin(angle) * planar]
})
const TOOL_NODE_INDICES = new Set([0, 3, 5])
const LEARNING_NODE_INDICES = new Set([1, 2, 6])

function hasWebGLSupport() {
  if (typeof window === 'undefined') return true

  try {
    const canvas = document.createElement('canvas')
    return Boolean(
      window.WebGLRenderingContext &&
        (canvas.getContext('webgl') || canvas.getContext('experimental-webgl')),
    )
  } catch {
    return false
  }
}

function MetisCoreMesh({ mode = 'idle', engaged = false, immersive = false }) {
  const groupRef = useRef(null)
  const shellRef = useRef(null)
  const shellMaterialRef = useRef(null)
  const nucleusRef = useRef(null)
  const orbitRef = useRef(null)
  const arcRef = useRef(null)
  const orbitMaterialRef = useRef(null)
  const coreMaterialRef = useRef(null)
  const connectionMaterialRef = useRef(null)
  const evaluationRingRef = useRef(null)
  const evaluationMaterialRef = useRef(null)
  const listeningPulseRef = useRef(null)
  const listeningPulseMaterialRef = useRef(null)
  const nodeRefs = useRef([])
  const nodeMaterialRefs = useRef([])
  const particleRefs = useRef([])
  const waveRefs = useRef([])
  const waveMaterialRefs = useRef([])
  const clockRef = useRef(0)
  const angularSpeedsRef = useRef({ shell: 0.6, orbit: 0.36, nucleus: 0.08 })
  const rotationRef = useRef({ shell: 0, orbit: 0, arc: 0, nucleus: 0 })
  const modeAgeRef = useRef(0)
  const previousModeRef = useRef(mode)
  const { glow, accent } = MODE_STYLES[mode] || MODE_STYLES.idle
  const isPlanning = mode === 'planning'
  const isProcessing = mode === 'processing'
  const isThinking = mode === 'thinking'
  const isListening = mode === 'listening'
  const isToolUse = mode === 'tool_use'
  const isEvaluating = mode === 'evaluating'
  const isLearning = mode === 'learning'
  const isSpeaking = mode === 'speaking'
  const isSuccess = mode === 'success'
  const isError = mode === 'error'

  const particles = useMemo(
    () =>
      Array.from({ length: 20 }, (_, index) => {
        const vertical = 1 - (2 * (index + 0.5)) / 20
        const planar = Math.sqrt(1 - vertical * vertical)
        const angle = index * Math.PI * (3 - Math.sqrt(5))
        return {
          direction: [Math.cos(angle) * planar, vertical, Math.sin(angle) * planar],
          distance: 1.12 + (index % 4) * 0.09,
          phase: index * 2.4,
          speed: 0.24 + (index % 5) * 0.035,
          size: 0.018 + (index % 3) * 0.006,
        }
      }),
    [],
  )
  const arcGeometry = useMemo(() => {
    const points = Array.from({ length: 42 }, (_, index) => {
      const angle = -0.8 + (index / 41) * 2.35
      return new THREE.Vector3(Math.cos(angle) * 1.48, Math.sin(angle) * 0.96, 0)
    })
    return new THREE.BufferGeometry().setFromPoints(points)
  }, [])
  const shellEdgeGeometry = useMemo(() => {
    const shellGeometry = new THREE.DodecahedronGeometry(1.2, 0)
    const edges = new THREE.EdgesGeometry(shellGeometry, 1)
    shellGeometry.dispose()
    return edges
  }, [])
  const connectionGeometry = useMemo(() => {
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(NODE_DIRECTIONS.length * 6), 3))
    geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1.6)
    return geometry
  }, [])

  useFrame((_, delta) => {
    const step = Math.min(delta, 0.05)
    clockRef.current += step
    if (previousModeRef.current !== mode) {
      previousModeRef.current = mode
      modeAgeRef.current = 0
    } else {
      modeAgeRef.current = Math.min(modeAgeRef.current + step, 4)
    }

    const time = clockRef.current
    const modeAge = modeAgeRef.current
    const transient = Math.exp(-modeAge * 2.4)
    const successStrength = isSuccess ? transient : 0
    const formation = isPlanning ? THREE.MathUtils.smoothstep(modeAge, 0, 1.35) : 1
    const statePulse = isListening
      ? Math.sin(time * 1.65) * (immersive ? 0.024 : 0.018)
      : isSpeaking
        ? Math.sin(time * 2.15) * (immersive ? 0.032 : 0.024)
        : isProcessing
          ? Math.sin(time * 1.1) * (immersive ? 0.016 : 0.012)
          : isThinking
            ? Math.sin(time * 1.4) * (immersive ? 0.016 : 0.01)
            : isSuccess
              ? Math.sin(modeAge * 8) * 0.045 * transient
              : 0
    const disruption = isError ? transient : 0

    if (groupRef.current) {
      groupRef.current.rotation.x = Math.sin(time * 0.13) * 0.009 + Math.sin(time * 8) * disruption * 0.008
      groupRef.current.rotation.y = Math.sin(time * 0.17) * 0.012
      groupRef.current.rotation.z = Math.cos(time * 0.11) * 0.006
    }

    const shellSpeed = isSpeaking ? 0.66 : isListening ? 0.68 : isProcessing ? 0.7 : isThinking ? 0.68 : isToolUse ? 0.64 : engaged ? 0.72 : immersive ? 0.64 : 0.6
    const orbitSpeed = isSpeaking ? 0.48 : isListening ? 0.46 : isProcessing ? 0.4 : isThinking ? 0.42 : isToolUse ? 0.42 : engaged ? 0.4 : immersive ? 0.4 : 0.36
    const nucleusSpeed = isSpeaking ? 0.14 : isListening ? 0.12 : isProcessing ? 0.13 : isThinking ? 0.11 : engaged ? 0.11 : immersive ? 0.1 : 0.08
    angularSpeedsRef.current.shell = THREE.MathUtils.damp(angularSpeedsRef.current.shell, shellSpeed, 3.5, step)
    angularSpeedsRef.current.orbit = THREE.MathUtils.damp(angularSpeedsRef.current.orbit, orbitSpeed, 3.5, step)
    angularSpeedsRef.current.nucleus = THREE.MathUtils.damp(angularSpeedsRef.current.nucleus, nucleusSpeed, 3.5, step)
    rotationRef.current.shell = (rotationRef.current.shell + angularSpeedsRef.current.shell * step) % TAU
    rotationRef.current.orbit = (rotationRef.current.orbit + angularSpeedsRef.current.orbit * step) % TAU
    rotationRef.current.arc = (rotationRef.current.arc + angularSpeedsRef.current.orbit * 0.72 * step) % TAU
    rotationRef.current.nucleus = (rotationRef.current.nucleus + angularSpeedsRef.current.nucleus * step) % TAU

    if (shellRef.current) {
      shellRef.current.rotation.x = 0.12 + Math.sin(time * 0.17) * 0.018
      shellRef.current.rotation.y = 0.08 + rotationRef.current.shell + Math.sin(time * 8) * disruption * 0.012
      shellRef.current.rotation.z = Math.cos(time * 0.13) * 0.014
    }
    if (shellMaterialRef.current) {
      shellMaterialRef.current.emissiveIntensity = immersive ? 0.16 : engaged ? 0.055 : 0.035
    }
    if (nucleusRef.current) {
      const nucleusPulse = Math.sin(time * (immersive ? 0.95 : 0.72)) * (immersive ? 0.018 : engaged ? 0.014 : 0.01)
      nucleusRef.current.rotation.y = rotationRef.current.nucleus
      nucleusRef.current.rotation.x = Math.sin(time * 0.2) * 0.025
      nucleusRef.current.scale.setScalar(1 + nucleusPulse + statePulse * 0.25)
    }
    if (orbitRef.current) {
      orbitRef.current.rotation.z = rotationRef.current.orbit
      orbitRef.current.rotation.x = 0.92 + Math.sin(time * 0.09) * 0.012
    }
    if (arcRef.current) {
      arcRef.current.rotation.y = -0.3 + rotationRef.current.arc
      arcRef.current.rotation.z = 0.46 + Math.sin(time * 0.12) * 0.012
    }
    if (orbitMaterialRef.current) {
      orbitMaterialRef.current.opacity = immersive ? 0.5 : engaged ? 0.35 : 0.3
    }
    if (coreMaterialRef.current) {
      const voiceLift = immersive ? 0.22 : 0
      const activityLift = isListening || isProcessing || isThinking || isSpeaking ? 0.12 : 0
      coreMaterialRef.current.emissiveIntensity = 0.16 + voiceLift + (engaged ? 0.08 : 0) + activityLift + (isSpeaking ? Math.sin(time * 2.15) * 0.1 : 0) + statePulse * 2
    }

    nodeRefs.current.forEach((node, index) => {
      if (!node) return
      const [x, y, z] = NODE_DIRECTIONS[index]
      const startDistance = isPlanning ? 1.55 : 1.08
      const nodeMotion = isThinking || isProcessing ? 0.45 : isListening || isSpeaking || immersive || engaged ? 0.34 : 0.28
      const nodeDrift = immersive ? 0.01 : engaged ? 0.008 : 0.005
      const distance = THREE.MathUtils.lerp(startDistance, 1.08, formation) + Math.sin(time * nodeMotion + index * 1.7) * nodeDrift
      node.position.set(
        x * distance + Math.sin(time * 0.38 + index * 2.1) * nodeDrift * 0.45,
        y * distance + Math.sin(time * 0.31 + index * 1.4 + 2) * nodeDrift * 0.35,
        z * distance + Math.cos(time * 0.35 + index * 1.8) * nodeDrift * 0.45,
      )
      const isActive = isPlanning || isThinking || isEvaluating || (isProcessing && index % 2 === 0) || (isToolUse && TOOL_NODE_INDICES.has(index)) || (isLearning && LEARNING_NODE_INDICES.has(index)) || (isListening && index % 2 === 0) || (isSpeaking && index % 2 === 1)
      node.scale.setScalar(isActive ? (isProcessing ? 0.036 : 0.043) : 0.025)
      if (nodeMaterialRefs.current[index]) {
        nodeMaterialRefs.current[index].emissiveIntensity = isActive
          ? 0.65 + Math.sin(time * 1.4 + index) * 0.12
          : 0.12 + successStrength * 0.53
        nodeMaterialRefs.current[index].opacity = isActive ? 0.95 : 0.56 + successStrength * 0.39
      }
    })

    const positions = connectionGeometry.getAttribute('position')
    NODE_DIRECTIONS.forEach((_, index) => {
      const node = nodeRefs.current[index]
      const start = index * 6
      positions.array[start] = 0
      positions.array[start + 1] = 0
      positions.array[start + 2] = 0
      const shouldConnect = index % 3 === 0 || isPlanning || isThinking || (isProcessing && index % 2 === 0) || (isToolUse && TOOL_NODE_INDICES.has(index)) || (isLearning && LEARNING_NODE_INDICES.has(index))
      positions.array[start + 3] = shouldConnect ? node?.position.x || 0 : 0
      positions.array[start + 4] = shouldConnect ? node?.position.y || 0 : 0
      positions.array[start + 5] = shouldConnect ? node?.position.z || 0 : 0
    })
    positions.needsUpdate = true
    if (connectionMaterialRef.current) {
      connectionMaterialRef.current.opacity = isPlanning ? 0.24 * formation : isThinking ? 0.2 : isProcessing ? 0.08 : isToolUse ? 0.2 : isLearning ? 0.18 : 0.055
    }

    particles.forEach((particle, index) => {
      const mesh = particleRefs.current[index]
      if (!mesh) return
      const [x, y, z] = particle.direction
      const pull = isListening ? 0.1 + (Math.sin(time * 1.3 + particle.phase) + 1) * 0.045 : 0
      const particleSpeed = particle.speed * (isListening ? 1.45 : isSpeaking || immersive ? 1.3 : engaged ? 1.2 : 1)
      const drift = isListening ? 0.04 : immersive ? 0.038 : engaged ? 0.034 : 0.03
      const distance = particle.distance * (1 - pull)
      mesh.position.set(
        x * distance + Math.sin(time * particleSpeed + particle.phase) * drift,
        y * distance + Math.cos(time * particleSpeed * 0.87 + particle.phase) * drift,
        z * distance + Math.sin(time * particleSpeed * 0.69 + particle.phase * 1.13) * drift,
      )
    })

    if (listeningPulseRef.current && listeningPulseMaterialRef.current) {
      const pulse = (time * 0.32) % 1
      listeningPulseRef.current.scale.setScalar(0.82 + pulse * 0.32)
      listeningPulseMaterialRef.current.opacity = isListening ? Math.sin(Math.PI * pulse) * 0.22 : 0
    }
    if (evaluationRingRef.current && evaluationMaterialRef.current) {
      evaluationRingRef.current.rotation.z = (time * 0.08) % TAU
      evaluationRingRef.current.scale.setScalar(1 + Math.sin(time * 0.7) * 0.015)
      evaluationMaterialRef.current.opacity = isEvaluating ? 0.2 : 0
    }
    waveRefs.current.forEach((wave, index) => {
      if (!wave) return
      const progress = (time * 0.12 + index * 0.48) % 1
      wave.scale.setScalar(0.9 + progress * 0.34)
      if (waveMaterialRefs.current[index]) {
        waveMaterialRefs.current[index].opacity = isSpeaking ? Math.sin(Math.PI * progress) * 0.12 : 0
      }
    })
  })

  return (
    <group ref={groupRef}>
      <group ref={shellRef}>
        <mesh>
          <dodecahedronGeometry args={[1.2, 0]} />
          <meshPhysicalMaterial
            ref={shellMaterialRef}
            color="#777777"
            emissive={glow}
            emissiveIntensity={0.08}
            transparent
            opacity={0.12}
            roughness={0.22}
            metalness={0.2}
            transmission={0.72}
            thickness={0.55}
            depthWrite={false}
          />
        </mesh>

        <lineSegments geometry={shellEdgeGeometry}>
          <lineBasicMaterial color={glow} transparent opacity={0.22} depthWrite={false} />
        </lineSegments>
      </group>

      <group ref={orbitRef} rotation={[0.92, 0.18, 0.22]}>
        <mesh scale={[1.08, 0.78, 0.72]}>
          <torusGeometry args={[1.48, 0.009, 6, 160]} />
          <meshBasicMaterial ref={orbitMaterialRef} color={accent} transparent opacity={0.3} />
        </mesh>
      </group>

      <line ref={arcRef} geometry={arcGeometry} rotation={[1.28, -0.3, 0.46]}>
        <lineBasicMaterial color={glow} transparent opacity={0.24} />
      </line>

      <lineSegments geometry={connectionGeometry}>
        <lineBasicMaterial ref={connectionMaterialRef} color={accent} transparent opacity={0} depthWrite={false} />
      </lineSegments>

      <mesh ref={evaluationRingRef} rotation={[1.24, 0.32, 0]}>
        <torusGeometry args={[1.58, 0.006, 6, 160]} />
        <meshBasicMaterial ref={evaluationMaterialRef} color={accent} transparent opacity={0} depthWrite={false} />
      </mesh>

      <mesh ref={listeningPulseRef}>
        <torusGeometry args={[1.18, 0.006, 6, 120]} />
        <meshBasicMaterial ref={listeningPulseMaterialRef} color={accent} transparent opacity={0} depthWrite={false} />
      </mesh>

      {[0, 1].map((index) => (
        <mesh
          key={index}
          ref={(node) => { waveRefs.current[index] = node }}
          scale={0.9}
        >
          <sphereGeometry args={[1.12, 20, 14]} />
          <meshBasicMaterial
            ref={(material) => { waveMaterialRefs.current[index] = material }}
            color={glow}
            wireframe
            transparent
            opacity={0}
            depthWrite={false}
          />
        </mesh>
      ))}

      <group ref={nucleusRef}>
        <mesh>
          <dodecahedronGeometry args={[0.5, 0]} />
          <meshStandardMaterial
            ref={coreMaterialRef}
            color={accent}
            emissive={glow}
            emissiveIntensity={0.42}
            metalness={0.35}
            roughness={0.22}
          />
        </mesh>
        <mesh scale={0.42} position={[0.02, 0.02, 0.02]}>
          <octahedronGeometry args={[0.46, 0]} />
          <meshBasicMaterial color="#f0f0f0" transparent opacity={immersive ? 0.82 : engaged ? 0.58 : 0.52} />
        </mesh>
      </group>

      {NODE_DIRECTIONS.map((_, index) => (
        <mesh
          key={`node-${index}`}
          ref={(node) => { nodeRefs.current[index] = node }}
          scale={0.025}
        >
          <sphereGeometry args={[1, 12, 12]} />
          <meshStandardMaterial
            ref={(material) => { nodeMaterialRefs.current[index] = material }}
            color={accent}
            emissive={glow}
            emissiveIntensity={0.12}
            transparent
            opacity={0.56}
          />
        </mesh>
      ))}

      {particles.map((particle, index) => (
        <mesh
          key={`particle-${index}`}
          ref={(node) => { particleRefs.current[index] = node }}
          scale={particle.size}
        >
          <sphereGeometry args={[1, 8, 8]} />
          <meshBasicMaterial color={index % 3 === 0 ? accent : glow} transparent opacity={0.72} />
        </mesh>
      ))}
    </group>
  )
}

function MetisCoreInner({ status = 'pending', mode: modeOverride, compact = false, immersive = false, engaged = false }) {
  const mode = modeOverride || STATE_MODE[status] || 'idle'

  return (
    <div className={`metis-3d-shell ${compact ? 'metis-3d-shell--compact' : ''} ${immersive ? 'metis-3d-shell--immersive' : ''}`}>
      <Canvas camera={{ position: [0, 0, immersive ? 5.5 : 4.65], fov: immersive ? 40 : 42 }} dpr={[1, 1.5]} gl={{ alpha: true, antialias: true }}>
        <ambientLight intensity={immersive ? 0.9 : engaged ? 0.56 : 0.5} />
        <pointLight position={[0, 0, 3.5]} intensity={immersive ? 5.2 : engaged ? 1.55 : 1.15} distance={8} color={MODE_STYLES[mode]?.glow || MODE_STYLES.idle.glow} />
        <pointLight position={[-2, 1, -2]} intensity={immersive ? 2.2 : engaged ? 0.65 : 0.55} distance={7} color="#c4c4c4" />
        <MetisCoreMesh mode={mode} engaged={engaged} immersive={immersive} />
      </Canvas>
    </div>
  )
}

export default function MetisCore({ status = 'pending', mode, compact = false, immersive = false, engaged = false }) {
  const supported = hasWebGLSupport()

  if (!supported) {
    return (
      <div className={`metis-fallback ${compact ? 'metis-fallback--compact' : ''} ${immersive ? 'metis-fallback--immersive' : ''} ${mode ? `metis-fallback--${mode}` : ''}`} aria-label="METIS core"><span>M</span></div>
    )
  }

    return <MetisCoreInner status={status} mode={mode} compact={compact} immersive={immersive} engaged={engaged} />
}
