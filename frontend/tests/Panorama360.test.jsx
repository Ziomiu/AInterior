import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Panorama360 from "../src/views/workflows/panorama-360/Panorama360";
import { downloadPanorama } from "../src/views/workflows/panorama-360/panoramaExport";
import { toaster } from "../src/components/ui/toaster";

vi.mock("axios");
vi.mock("../src/views/workflows/panorama-360/panoramaExport", () => ({ downloadPanorama: vi.fn() }));
vi.mock("../src/components/ui/toaster", () => ({ toaster: { create: vi.fn() } }));
vi.mock("../src/views/workflows/panorama-360/PanoramaViewer", () => ({
  default: () => <img alt="Interactive 360-degree panorama" />,
}));

beforeEach(() => {
  vi.spyOn(localStorage, "getItem").mockImplementation(key => key === "token" ? "example-token" : null);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

async function renderGeneratedPanorama() {
  axios.post.mockResolvedValueOnce({ data: { image: "panorama-data" } });
  render(<MemoryRouter><Panorama360 /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Generate 360 image" }));
  await screen.findByRole("img", { name: "Interactive 360-degree panorama" });
}

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

  it("does not offer downloads before a panorama exists", () => {
    render(<MemoryRouter><Panorama360 /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: "Download panorama" })).not.toBeInTheDocument();
  });

  it("downloads JPEG with 360 metadata by default", async () => {
    await renderGeneratedPanorama();
    expect(screen.getByRole("combobox", { name: "Download format" })).toHaveValue("jpeg");
    fireEvent.click(screen.getByRole("button", { name: "Download panorama" }));
    await waitFor(() => expect(downloadPanorama).toHaveBeenCalledWith("panorama-data", "jpeg"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Download panorama" })).toBeEnabled());
  });

  it("downloads the selected PNG format from the flat preview", async () => {
    await renderGeneratedPanorama();
    fireEvent.click(screen.getByRole("button", { name: "Flat image" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Download format" }), { target: { value: "png" } });
    fireEvent.click(screen.getByRole("button", { name: "Download panorama" }));
    await waitFor(() => expect(downloadPanorama).toHaveBeenCalledWith("panorama-data", "png"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Download panorama" })).toBeEnabled());
  });

  it("prevents duplicate exports and generation while preparing a file", async () => {
    let complete;
    downloadPanorama.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    await renderGeneratedPanorama();
    fireEvent.click(screen.getByRole("button", { name: "Download panorama" }));
    expect(screen.getByRole("button", { name: "Download panorama" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Download format" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeDisabled();
    await act(async () => { complete(); });
    expect(screen.getByRole("button", { name: "Download panorama" })).toBeEnabled();
  });

  it("reports export failure and allows retrying", async () => {
    downloadPanorama.mockRejectedValueOnce(new Error("Image decode failed"));
    await renderGeneratedPanorama();
    fireEvent.click(screen.getByRole("button", { name: "Download panorama" }));
    await waitFor(() => expect(toaster.create).toHaveBeenCalledWith(expect.objectContaining({
      title: "Panorama download failed", description: "Image decode failed", status: "error",
    })));
    expect(screen.getByRole("button", { name: "Download panorama" })).toBeEnabled();
  });

  it("disables downloads while generating a replacement panorama", async () => {
    await renderGeneratedPanorama();
    let complete;
    axios.post.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    fireEvent.click(screen.getByRole("button", { name: "Generate 360 image" }));
    expect(screen.getByRole("button", { name: "Download panorama" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Download format" })).toBeDisabled();
    await act(async () => { complete({ data: { image: "new-panorama" } }); });
    expect(screen.getByRole("button", { name: "Download panorama" })).toBeEnabled();
  });
});