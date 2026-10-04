import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Panorama360 from "../src/views/workflows/panorama-360/Panorama360";

vi.mock("axios");
vi.mock("../src/views/workflows/panorama-360/PanoramaViewer", () => ({
  default: () => <img alt="Interactive 360-degree panorama" />,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Panorama360", () => {
  it("submits a bounded 2:1 prompt and displays the interactive result", async () => {
    vi.spyOn(localStorage, "getItem").mockImplementation((key) => key === "token" ? "example-token" : null);
    axios.post.mockResolvedValueOnce({ data: { image: "panorama-data" } });
    render(<MemoryRouter><Panorama360 /></MemoryRouter>);

    await fireEvent.click(screen.getByRole("button", { name: "Generate 360 image" }));

    expect(axios.post).toHaveBeenCalledWith(
      "/api/model/generate/text-to-image",
      expect.objectContaining({
        model_version: "xl",
        width: 1024,
        height: 512,
        prompt: expect.stringContaining("seamless equirectangular 360-degree architectural panorama"),
      }),
      { headers: { Authorization: "Bearer example-token" } }
    );
    expect(await screen.findByRole("img", { name: "Interactive 360-degree panorama" })).toBeInTheDocument();
  });
});