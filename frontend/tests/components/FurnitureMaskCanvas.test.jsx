import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FurnitureMaskCanvas, { imageCoordinates } from "../../src/components/FurnitureMaskCanvas";

describe("Furniture coordinates", () => {
  const canvas = { width: 1000, height: 500, getBoundingClientRect: () => ({ left: 10, top: 20, width: 500, height: 250 }) };
  it("converts displayed positions to native image coordinates", () => {
    expect(imageCoordinates({ clientX: 260, clientY: 145 }, canvas)).toEqual({ x: 500, y: 250 });
  });
  it("clamps edge clicks inside the image", () => {
    expect(imageCoordinates({ clientX: 510, clientY: 270 }, canvas)).toEqual({ x: 999, y: 499 });
  });
  it("clamps clicks outside the top-left corner to the first pixel", () => {
    expect(imageCoordinates({ clientX: -30, clientY: -40 }, canvas)).toEqual({ x: 0, y: 0 });
  });
  it("rounds scaled fractional positions to native pixels", () => {
    expect(imageCoordinates({ clientX: 10.25, clientY: 20.75 }, canvas)).toEqual({ x: 1, y: 2 });
  });
});

describe("Furniture mask selection", () => {
  beforeEach(() => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    vi.stubGlobal("Image", class {
      naturalWidth = 1000;
      naturalHeight = 500;
      set src(value) { queueMicrotask(() => this.onload?.()); }
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      clearRect: vi.fn(), drawImage: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(), stroke: vi.fn(),
    });
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  const renderEditor = async (tool = "select", disabled = false) => {
    const onPoint = vi.fn();
    const onMaskChange = vi.fn();
    render(<FurnitureMaskCanvas image="data:image/png;base64,room" mask={null} points={[]} tool={tool}
      brushSize={24} disabled={disabled} onPoint={onPoint} onMaskChange={onMaskChange} />);
    const canvas = screen.getByLabelText("Furniture mask editor");
    await waitFor(() => expect(canvas).toHaveAttribute("width", "1000"));
    expect(canvas).toHaveAttribute("height", "500");
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({ left: 10, top: 20, width: 500, height: 250 });
    return { canvas, onPoint, onMaskChange };
  };

  it.each([
    ["select", {}, 1],
    ["include", {}, 1],
    ["exclude", {}, 0],
    ["select", { shiftKey: true }, 0],
    ["select", { button: 2 }, 0],
  ])("emits native pixel coordinates for %s with modifiers %j and label %s", async (tool, modifiers, label) => {
    const { canvas, onPoint, onMaskChange } = await renderEditor(tool);
    fireEvent.pointerDown(canvas, { clientX: 260, clientY: 145, ...modifiers });
    fireEvent.pointerUp(canvas);
    expect(onPoint).toHaveBeenCalledExactlyOnceWith({ x: 500, y: 250, label });
    expect(onMaskChange).not.toHaveBeenCalled();
  });

  it("ignores selection events when disabled", async () => {
    const { canvas, onPoint, onMaskChange } = await renderEditor("select", true);
    fireEvent.pointerDown(canvas, { clientX: 260, clientY: 145 });
    fireEvent.pointerUp(canvas);
    expect(onPoint).not.toHaveBeenCalled();
    expect(onMaskChange).not.toHaveBeenCalled();
  });

  it("does not paint or emit points before a mask exists", async () => {
    const { canvas, onPoint, onMaskChange } = await renderEditor("paint");
    fireEvent.pointerDown(canvas, { clientX: 260, clientY: 145 });
    fireEvent.pointerMove(canvas, { clientX: 270, clientY: 155 });
    fireEvent.pointerUp(canvas);
    expect(onPoint).not.toHaveBeenCalled();
    expect(onMaskChange).not.toHaveBeenCalled();
  });
});