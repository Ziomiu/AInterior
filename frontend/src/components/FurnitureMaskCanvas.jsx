import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

export function imageCoordinates(event, canvas) {
  const bounds = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(canvas.width - 1, Math.round((event.clientX - bounds.left) * canvas.width / bounds.width))),
    y: Math.max(0, Math.min(canvas.height - 1, Math.round((event.clientY - bounds.top) * canvas.height / bounds.height))),
  };
}

const FurnitureMaskCanvas = forwardRef(function FurnitureMaskCanvas({ image, mask, points, tool, brushSize, disabled, onPoint, onMaskChange }, ref) {
  const canvasRef = useRef(null);
  const photoRef = useRef(null);
  const maskRef = useRef(null);
  const drawingRef = useRef(false);
  const previousRef = useRef(null);
  const undoRef = useRef([]);

  const redraw = () => {
    const canvas = canvasRef.current;
    const photo = photoRef.current;
    if (!canvas || !photo) return;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(photo, 0, 0, canvas.width, canvas.height);
    if (maskRef.current) {
      const tinted = document.createElement("canvas");
      tinted.width = canvas.width;
      tinted.height = canvas.height;
      const overlay = tinted.getContext("2d");
      overlay.drawImage(maskRef.current, 0, 0);
      const pixels = overlay.getImageData(0, 0, tinted.width, tinted.height);
      for (let index = 0; index < pixels.data.length; index += 4) {
        const selected = pixels.data[index] > 127;
        pixels.data[index] = 120;
        pixels.data[index + 1] = 142;
        pixels.data[index + 2] = 109;
        pixels.data[index + 3] = selected ? 125 : 0;
      }
      overlay.putImageData(pixels, 0, 0);
      context.drawImage(tinted, 0, 0);
    }
    points.forEach(point => {
      context.beginPath();
      context.arc(point.x, point.y, Math.max(5, canvas.width / 130), 0, Math.PI * 2);
      context.fillStyle = point.label ? "#788e6d" : "#b74b42";
      context.fill();
      context.strokeStyle = "#ffffff";
      context.lineWidth = 2;
      context.stroke();
    });
  };

  useEffect(() => {
    let active = true;
    undoRef.current = [];
    maskRef.current = null;
    const photo = new Image();
    photo.onload = () => {
      if (!active) return;
      photoRef.current = photo;
      canvasRef.current.width = photo.naturalWidth;
      canvasRef.current.height = photo.naturalHeight;
      redraw();
    };
    photo.src = image;
    return () => { active = false; };
  }, [image]);

  useEffect(() => {
    let active = true;
    if (!mask) {
      maskRef.current = null;
      redraw();
      return;
    }
    const source = new Image();
    source.onload = () => {
      if (!active) return;
      const next = document.createElement("canvas");
      next.width = source.naturalWidth;
      next.height = source.naturalHeight;
      next.getContext("2d").drawImage(source, 0, 0);
      maskRef.current = next;
      redraw();
    };
    source.src = mask;
    return () => { active = false; };
  }, [mask]);

  useEffect(redraw, [points]);

  useImperativeHandle(ref, () => ({
    undo() {
      const previous = undoRef.current.pop();
      if (previous) onMaskChange(previous);
    },
  }));

  const paint = position => {
    const context = maskRef.current.getContext("2d");
    context.strokeStyle = tool === "erase" ? "black" : "white";
    context.fillStyle = context.strokeStyle;
    context.lineWidth = brushSize;
    context.lineCap = "round";
    context.beginPath();
    context.moveTo(previousRef.current.x, previousRef.current.y);
    context.lineTo(position.x, position.y);
    context.stroke();
    context.beginPath();
    context.arc(position.x, position.y, brushSize / 2, 0, Math.PI * 2);
    context.fill();
    previousRef.current = position;
    redraw();
  };

  const start = event => {
    if (disabled || !photoRef.current) return;
    const canvas = canvasRef.current;
    const position = imageCoordinates(event, canvas);
    if (tool === "select" || tool === "include" || tool === "exclude") {
      onPoint({ ...position, label: event.shiftKey || event.button === 2 || tool === "exclude" ? 0 : 1 });
      return;
    }
    if (!maskRef.current) return;
    undoRef.current.push(maskRef.current.toDataURL("image/png"));
    undoRef.current = undoRef.current.slice(-10);
    drawingRef.current = true;
    canvas.setPointerCapture(event.pointerId);
    previousRef.current = position;
    paint(position);
  };

  const stop = () => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    onMaskChange(maskRef.current.toDataURL("image/png"));
  };

  return <canvas ref={canvasRef} aria-label="Furniture mask editor" className="block w-full h-auto touch-none cursor-crosshair"
    onContextMenu={event => event.preventDefault()} onPointerDown={start}
    onPointerMove={event => { if (drawingRef.current) paint(imageCoordinates(event, canvasRef.current)); }}
    onPointerUp={stop} onPointerCancel={stop} />;
});

export default FurnitureMaskCanvas;