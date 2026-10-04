import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import FurnitureReplace, { waitForFurnitureJob } from "../src/views/workflows/furniture-replace/FurnitureReplace";

vi.mock("axios");
vi.mock("../src/components/FurnitureMaskCanvas", () => ({ default: ({ onPoint }) => <div data-testid="mask-editor"><button onClick={() => onPoint({ x: 10, y: 10, label: 1 })}>Add point</button></div> }));

beforeEach(() => {
  localStorage.setItem("token", "test-token");
  axios.get.mockImplementation(url => Promise.resolve({ data: url.endsWith("products") ? { products: [] } : { status: "ok" } }));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });

describe("Furniture Replace", () => {
  it("renders the existing workflow vocabulary with generation gated by mask acceptance", async () => {
    render(<FurnitureReplace />);
    expect(screen.getByRole("heading", { name: "Furniture Replace" })).toBeInTheDocument();
    expect(await screen.findByText("Service ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace furniture" })).toBeDisabled();
    expect(axios.get).toHaveBeenCalledWith("/api/furniture/health", expect.objectContaining({ headers: { Authorization: "Bearer test-token" } }));
  });
  it("loads an image passed from the gallery", async () => {
    localStorage.setItem("selectedImage", JSON.stringify({ image_base64: "fixture", prompt: "red chair" }));
    render(<FurnitureReplace />);
    expect(await screen.findByTestId("mask-editor")).toBeInTheDocument();
    expect(screen.getByDisplayValue("red chair")).toBeInTheDocument();
    expect(localStorage.getItem("selectedImage")).toBeNull();
  });
  it("shows service failure without enabling generation", async () => {
    axios.get.mockRejectedValue(new Error("offline"));
    render(<FurnitureReplace />);
    expect(await screen.findByText("Service unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace furniture" })).toBeDisabled();
  });
  it("supports an accessible fixed seed control", async () => {
    render(<FurnitureReplace />);
    await userEvent.click(screen.getByText("Parameters", { exact: true }));
    expect(screen.getByRole("spinbutton", { name: "Seed" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "Random seed" }));
    expect(screen.getByRole("spinbutton", { name: "Seed" })).toBeEnabled();
  });
  it("invalidates an accepted mask when a new point is added", async () => {
    localStorage.setItem("selectedImage", JSON.stringify({ image_base64: "fixture", prompt: "red chair" }));
    axios.post.mockResolvedValue({ data: { job_id: "mask-job" } });
    axios.get.mockImplementation(url => Promise.resolve({ data: url.includes("/jobs/")
      ? { status: "done", result: { mask: "mask" } }
      : url.endsWith("products") ? { products: [] } : { status: "ok" } }));
    render(<FurnitureReplace />);
    await screen.findByText("Service ready");
    await userEvent.click(screen.getByRole("button", { name: "Add point" }));
    await userEvent.click(screen.getByRole("button", { name: "Segment" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Accept mask" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Accept mask" }));
    expect(screen.getByRole("button", { name: "Replace furniture" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Add point" }));
    expect(screen.getByRole("button", { name: "Accept mask" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Replace furniture" })).toBeDisabled();
  });
  it("switches to reference controls and renders catalog names as text", async () => {
    axios.get.mockImplementation(url => Promise.resolve({ data: url.endsWith("products") ? {
      products: [{ product_id: "chair", name: "<b>Chair</b>", image: "fixture" }],
    } : {} }));
    render(<FurnitureReplace />);
    await userEvent.click(screen.getByRole("tab", { name: "reference" }));
    expect(await screen.findByText("<b>Chair</b>")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find matches" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Replace furniture" })).toBeDisabled();
  });
  it("returns completed jobs and surfaces inference failures", async () => {
    const signal = new AbortController().signal;
    axios.get.mockResolvedValueOnce({ data: { status: "done", result: { image: "result" } } });
    expect(await waitForFurnitureJob("job", signal, vi.fn())).toEqual({ image: "result" });
    axios.get.mockResolvedValueOnce({ data: { status: "failed", error: "GPU busy" } });
    await expect(waitForFurnitureJob("job", signal, vi.fn())).rejects.toThrow("GPU busy");
  });
  it("does not send an old prompt or Quality profile with a catalog reference", async () => {
    localStorage.setItem("selectedImage", JSON.stringify({ image_base64: "fixture", prompt: "old red chair prompt" }));
    axios.post.mockResolvedValue({ data: { job_id: "job" } });
    axios.get.mockImplementation(url => Promise.resolve({ data: url.includes("/jobs/")
      ? { status: "done", result: { mask: "mask", image: "result" } }
      : url.endsWith("products") ? { products: [{ product_id: "chair", name: "Blue chair", image: "reference" }] }
      : { status: "ok" } }));
    render(<FurnitureReplace />);
    await screen.findByText("Service ready");
    await userEvent.click(screen.getByRole("button", { name: "Add point" }));
    await userEvent.click(screen.getByRole("button", { name: "Segment" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Accept mask" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Accept mask" }));
    await userEvent.click(screen.getByRole("button", { name: "quality", exact: true }));
    await userEvent.click(screen.getByRole("tab", { name: "reference" }));
    await userEvent.click(screen.getByRole("button", { name: /Blue chair/ }));
    await userEvent.click(screen.getByRole("button", { name: "Replace furniture" }));
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith("/api/furniture/replace", expect.objectContaining({
      mode: "reference", product_id: "chair", quality: "balanced", prompt: undefined,
    }), expect.any(Object)));
  });
});