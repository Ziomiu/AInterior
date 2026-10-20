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
  axios.get.mockResolvedValue({ data: { models: [
    { id: "realvisxl-v4", label: "RealVisXL V4 - realistic interiors", width: 1536, height: 768 },
    { id: "sdxl-base", label: "SDXL Base - general purpose", width: 1536, height: 768 },
  ], qualities: ["draft", "high"] } });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

async function renderGeneratedPanorama() {
  axios.post.mockResolvedValueOnce({ data: { image: "panorama-data" } });
  render(<MemoryRouter><Panorama360 /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Generate 360 image" }));
  await screen.findByRole("img", { name: "Interactive 360-degree panorama" });
}

describe("Panorama360", () => {
  it("submits the selected profile and repeatable seed and displays the interactive result", async () => {
    vi.spyOn(localStorage, "getItem").mockImplementation((key) => key === "token" ? "example-token" : null);
    axios.post.mockResolvedValueOnce({ data: { image: "panorama-data" } });
    render(<MemoryRouter><Panorama360 /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeEnabled());
    fireEvent.change(screen.getByRole("spinbutton", { name: "Seed" }), { target: { value: "42" } });
    await fireEvent.click(screen.getByRole("button", { name: "Generate 360 image" }));

    expect(axios.post).toHaveBeenCalledWith(
      "/api/model/generate/panorama",
      expect.objectContaining({
        model_id: "realvisxl-v4",
        seed: 42,
        quality: "draft",
        brief: expect.stringContaining("exhibition space"),
      }),
      { headers: { Authorization: "Bearer example-token" } }
    );
    expect(await screen.findByRole("img", { name: "Interactive 360-degree panorama" })).toBeInTheDocument();
  });

  it("uses the selected installed model", async () => {
    axios.post.mockResolvedValueOnce({ data: { image: "panorama-data" } });
    render(<MemoryRouter><Panorama360 /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("realvisxl-v4"));
    fireEvent.change(screen.getByRole("combobox", { name: "Model" }), { target: { value: "sdxl-base" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate 360 image" }));
    await screen.findByRole("img", { name: "Interactive 360-degree panorama" });
    expect(axios.post.mock.calls[0][1].model_id).toBe("sdxl-base");
  });

  it("submits High quality and preserves the generated result dimensions when controls change", async () => {
    axios.post.mockResolvedValueOnce({ data: { image: "panorama-data" } });
    render(<MemoryRouter><Panorama360 /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeEnabled());
    fireEvent.click(screen.getByRole("radio", { name: "High / 4K" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate 360 image" }));
    await screen.findByRole("img", { name: "Interactive 360-degree panorama" });
    expect(axios.post.mock.calls[0][1].quality).toBe("high");
    expect(screen.getByRole("heading", { name: "Preview - 4096 x 2048" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Draft" }));
    expect(screen.getByRole("heading", { name: "Preview - 4096 x 2048" })).toBeInTheDocument();
  });

  it("disables High when server processing is unavailable", async () => {
    axios.get.mockResolvedValueOnce({ data: { models: [{ id: "sdxl-base", label: "SDXL Base" }], qualities: ["draft"] } });
    render(<MemoryRouter><Panorama360 /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeEnabled());
    expect(screen.getByRole("radio", { name: "High / 4K" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Draft" })).toBeChecked();
  });

  it("blocks generation until the inventory is loaded", async () => {
    let complete;
    axios.get.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    render(<MemoryRouter><Panorama360 /></MemoryRouter>);
    expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeDisabled();
    await act(async () => { complete({ data: { models: [] } }); });
    expect(screen.getByRole("alert")).toHaveTextContent("No panorama models are installed");
    expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeDisabled();
  });

  it("allows retrying a failed model inventory request", async () => {
    axios.get.mockRejectedValueOnce(new Error("unavailable"));
    render(<MemoryRouter><Panorama360 /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load panorama models");
    fireEvent.click(screen.getByRole("button", { name: "Reload models" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeEnabled());
  });

  it("rejects blank briefs and invalid seeds", async () => {
    render(<MemoryRouter><Panorama360 /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeEnabled());
    fireEvent.change(screen.getByRole("spinbutton", { name: "Seed" }), { target: { value: "-1" } });
    expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeDisabled();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Seed" }), { target: { value: "42" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Exhibition space brief" }), { target: { value: "  " } });
    expect(screen.getByRole("button", { name: "Generate 360 image" })).toBeDisabled();
    expect(axios.post).not.toHaveBeenCalled();
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