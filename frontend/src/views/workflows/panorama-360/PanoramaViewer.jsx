import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { MdRefresh } from "react-icons/md";

export default function PanoramaViewer({ imageBase64 }) {
  const hostRef = useRef(null);
  const resetRef = useRef(() => {});
  const [webglUnavailable, setWebglUnavailable] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;

    let renderer;
    let texture;
    let frameId;
    let dragging = false;
    let previousX = 0;
    let previousY = 0;
    let yaw = 0;
    let pitch = 0;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, 1, 0.1, 1100);
    camera.position.set(0, 0, 0);
    camera.rotation.order = "YXZ";

    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.domElement.className = "h-full w-full touch-none cursor-grab";
      renderer.domElement.tabIndex = 0;
      renderer.domElement.setAttribute("role", "application");
      renderer.domElement.setAttribute("aria-label", "Interactive 360 panorama. Use arrow keys to look around and plus or minus to zoom.");
      host.appendChild(renderer.domElement);
    } catch {
      setWebglUnavailable(true);
      return undefined;
    }

    const resize = () => {
      const width = Math.max(host.clientWidth, 1);
      const height = Math.max(host.clientHeight, 1);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };

    const applyView = () => {
      camera.rotation.y = yaw;
      camera.rotation.x = pitch;
    };

    resetRef.current = () => {
      yaw = 0;
      pitch = 0;
      camera.fov = 75;
      camera.updateProjectionMatrix();
      applyView();
    };

    const onPointerDown = (event) => {
      dragging = true;
      previousX = event.clientX;
      previousY = event.clientY;
      renderer.domElement.setPointerCapture(event.pointerId);
      renderer.domElement.classList.replace("cursor-grab", "cursor-grabbing");
    };
    const onPointerMove = (event) => {
      if (!dragging) return;
      yaw -= (event.clientX - previousX) * 0.004;
      pitch = THREE.MathUtils.clamp(pitch - (event.clientY - previousY) * 0.004, -1.45, 1.45);
      previousX = event.clientX;
      previousY = event.clientY;
      applyView();
    };
    const onPointerUp = () => {
      dragging = false;
      renderer.domElement.classList.replace("cursor-grabbing", "cursor-grab");
    };
    const onWheel = (event) => {
      camera.fov = THREE.MathUtils.clamp(camera.fov + Math.sign(event.deltaY) * 3, 35, 100);
      camera.updateProjectionMatrix();
    };
    const onKeyDown = (event) => {
      const step = 0.08;
      if (event.key === "ArrowLeft") yaw += step;
      else if (event.key === "ArrowRight") yaw -= step;
      else if (event.key === "ArrowUp") pitch = THREE.MathUtils.clamp(pitch + step, -1.45, 1.45);
      else if (event.key === "ArrowDown") pitch = THREE.MathUtils.clamp(pitch - step, -1.45, 1.45);
      else if (event.key === "+" || event.key === "=") camera.fov = THREE.MathUtils.clamp(camera.fov - 3, 35, 100);
      else if (event.key === "-") camera.fov = THREE.MathUtils.clamp(camera.fov + 3, 35, 100);
      else return;
      event.preventDefault();
      camera.updateProjectionMatrix();
      applyView();
    };

    const loader = new THREE.TextureLoader();
    texture = loader.load(`data:image/png;base64,${imageBase64}`);
    texture.colorSpace = THREE.SRGBColorSpace;
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(500, 48, 32),
      new THREE.MeshBasicMaterial({ map: texture, side: THREE.BackSide })
    );
    scene.add(sphere);

    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("pointerup", onPointerUp);
    renderer.domElement.addEventListener("pointercancel", onPointerUp);
    renderer.domElement.addEventListener("wheel", onWheel, { passive: true });
    renderer.domElement.addEventListener("keydown", onKeyDown);
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    const render = () => {
      renderer.render(scene, camera);
      frameId = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      window.cancelAnimationFrame(frameId);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      renderer.domElement.removeEventListener("pointercancel", onPointerUp);
      renderer.domElement.removeEventListener("wheel", onWheel);
      renderer.domElement.removeEventListener("keydown", onKeyDown);
      texture.dispose();
      sphere.geometry.dispose();
      sphere.material.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [imageBase64]);

  return (
    <div ref={hostRef} className="relative h-full min-h-[300px] w-full" aria-label="360 panorama preview">
      {webglUnavailable && (
        <img src={`data:image/png;base64,${imageBase64}`} alt="Generated equirectangular exhibition-space panorama" className="h-full min-h-[300px] w-full object-contain" />
      )}
      <button
        type="button"
        onClick={() => resetRef.current()}
        aria-label="Reset panorama view"
        title="Reset view"
        className="absolute right-3 top-3 grid h-10 w-10 place-items-center rounded bg-black/60 text-white hover:bg-black/80"
      >
        <MdRefresh aria-hidden="true" className="h-5 w-5" />
      </button>
    </div>
  );
}