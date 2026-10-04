import { describe, expect, it } from "vitest";
import { imageCoordinates } from "../../src/components/FurnitureMaskCanvas";

describe("Furniture coordinates", () => {
  const canvas = { width: 1000, height: 500, getBoundingClientRect: () => ({ left: 10, top: 20, width: 500, height: 250 }) };
  it("converts displayed positions to native image coordinates", () => {
    expect(imageCoordinates({ clientX: 260, clientY: 145 }, canvas)).toEqual({ x: 500, y: 250 });
  });
  it("clamps edge clicks inside the image", () => {
    expect(imageCoordinates({ clientX: 510, clientY: 270 }, canvas)).toEqual({ x: 999, y: 499 });
  });
});