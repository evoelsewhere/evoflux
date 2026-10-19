import type { Scene3DSpec } from '@/api/types'

export interface SceneRuntime {
  setVisible(visible: boolean): void
  setReducedMotion(enabled: boolean): void
  resetCamera(): void
  dispose(): void
}

type ThreeApi = typeof import('three')

const semanticTokens: Record<Scene3DSpec['nodes'][number]['color'], string> = {
  accent: '--color-accent', foreground: '--color-text-primary', muted: '--color-text-subtle',
  success: '--color-success', warning: '--color-warning', danger: '--color-danger', info: '--color-info',
}

export function calculateSceneCameraDistance(radius: number, verticalFovDegrees: number, aspect: number): number {
  const safeAspect = Math.min(1, Math.max(0.1, aspect))
  const verticalHalfFov = (verticalFovDegrees * Math.PI) / 360
  const limitingHalfFov = Math.atan(Math.tan(verticalHalfFov) * safeAspect)
  return Math.max(3, (Math.max(radius, 0.5) / Math.sin(limitingHalfFov)) * 1.15)
}

export function createSceneRuntime(
  canvas: HTMLCanvasElement,
  sceneSpec: Scene3DSpec,
  options: { reducedMotion: boolean; maxPixelRatio: number; three: ThreeApi },
): SceneRuntime {
  const THREE = options.three
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, options.maxPixelRatio, 2))
  const scene = new THREE.Scene()
  scene.background = null
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 1_000)
  camera.position.set(0, 1.5, 8)
  const group = new THREE.Group()
  scene.add(group)
  scene.add(new THREE.HemisphereLight(0xffffff, 0x526078, 2.2))
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.5)
  keyLight.position.set(4, 7, 6)
  scene.add(keyLight)
  const materials: Array<{ dispose(): void }> = []
  const geometries: Array<{ dispose(): void }> = []
  const rootStyles = getComputedStyle(document.documentElement)

  for (const node of sceneSpec.nodes) {
    let geometry:
      | InstanceType<ThreeApi['SphereGeometry']>
      | InstanceType<ThreeApi['CylinderGeometry']>
      | InstanceType<ThreeApi['TorusGeometry']>
      | InstanceType<ThreeApi['BoxGeometry']>
    if (node.geometry === 'sphere') geometry = new THREE.SphereGeometry(0.65, 24, 16)
    else if (node.geometry === 'cylinder') geometry = new THREE.CylinderGeometry(0.5, 0.5, 1, 24)
    else if (node.geometry === 'torus') geometry = new THREE.TorusGeometry(0.55, 0.18, 12, 40)
    else geometry = new THREE.BoxGeometry(1, 1, 1)
    const token = semanticTokens[node.color]
    const color = rootStyles.getPropertyValue(token).trim() || '#6d7cff'
    const material = new THREE.MeshStandardMaterial({ color, roughness: 0.46, metalness: 0.12 })
    const mesh = new THREE.Mesh(geometry, material)
    mesh.position.set(...node.position)
    mesh.rotation.set(...node.rotation)
    mesh.scale.set(...node.scale)
    mesh.userData.label = node.label ?? node.id
    group.add(mesh)
    geometries.push(geometry)
    materials.push(material)
  }

  let visible = true
  let reducedMotion = options.reducedMotion
  let disposed = false
  let dragging = false
  let lastX = 0
  let lastY = 0
  const bounds = new THREE.Box3().setFromObject(group)
  const center = new THREE.Vector3()
  const sphere = new THREE.Sphere()
  bounds.getBoundingSphere(sphere)
  bounds.getCenter(center)
  const initialAspect = (canvas.clientWidth || 640) / (canvas.clientHeight || 360)
  const initialDistance = calculateSceneCameraDistance(sphere.radius, camera.fov, initialAspect)
  camera.position.set(center.x, center.y + initialDistance * 0.12, center.z + initialDistance)
  camera.lookAt(center)
  const initialCamera = camera.position.clone()
  const initialTarget = center.clone()
  const resize = () => {
    const width = Math.max(1, Math.min(canvas.clientWidth || 640, 1920))
    const height = Math.max(1, Math.min(canvas.clientHeight || 360, 1080))
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    render()
  }
  const render = () => { if (!disposed) renderer.render(scene, camera) }
  let lastFrameAt = 0
  const tick = (time = performance.now()) => {
    if (time - lastFrameAt < 33) return
    lastFrameAt = time
    if (!dragging) group.rotation.y += 0.002
    render()
  }
  const syncLoop = () => {
    if (disposed) return
    if (!visible || reducedMotion) renderer.setAnimationLoop(null)
    else renderer.setAnimationLoop(tick)
    render()
  }
  const pointerDown = (event: PointerEvent) => { dragging = true; lastX = event.clientX; lastY = event.clientY; canvas.setPointerCapture?.(event.pointerId) }
  const pointerMove = (event: PointerEvent) => {
    if (!dragging) return
    group.rotation.y += (event.clientX - lastX) * 0.008
    group.rotation.x += (event.clientY - lastY) * 0.008
    lastX = event.clientX; lastY = event.clientY; render()
  }
  const pointerUp = () => { dragging = false }
  const keyDown = (event: KeyboardEvent) => {
    const step = event.shiftKey ? 0.2 : 0.08
    if (event.key === 'ArrowLeft') group.rotation.y -= step
    else if (event.key === 'ArrowRight') group.rotation.y += step
    else if (event.key === 'ArrowUp') group.rotation.x -= step
    else if (event.key === 'ArrowDown') group.rotation.x += step
    else return
    event.preventDefault(); render()
  }
  const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null
  observer?.observe(canvas)
  canvas.addEventListener('pointerdown', pointerDown)
  canvas.addEventListener('pointermove', pointerMove)
  canvas.addEventListener('pointerup', pointerUp)
  canvas.addEventListener('pointercancel', pointerUp)
  canvas.addEventListener('keydown', keyDown)
  resize()
  syncLoop()

  return {
    setVisible(next) { visible = next; syncLoop() },
    setReducedMotion(next) { reducedMotion = next; syncLoop() },
    resetCamera() { camera.position.copy(initialCamera); camera.lookAt(initialTarget); group.rotation.set(0, 0, 0); render() },
    dispose() {
      if (disposed) return
      disposed = true
      observer?.disconnect()
      renderer.setAnimationLoop(null)
      canvas.removeEventListener('pointerdown', pointerDown)
      canvas.removeEventListener('pointermove', pointerMove)
      canvas.removeEventListener('pointerup', pointerUp)
      canvas.removeEventListener('pointercancel', pointerUp)
      canvas.removeEventListener('keydown', keyDown)
      geometries.forEach((geometry) => geometry.dispose())
      materials.forEach((material) => material.dispose())
      renderer.dispose()
    },
  }
}
