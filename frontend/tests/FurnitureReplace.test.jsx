import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import FurnitureReplace, { waitForFurnitureJob } from "../src/views/workflows/furniture-replace/FurnitureReplace";

vi.mock("axios");
vi.mock("../src/components/FurnitureMaskCanvas", async () => {
  const { forwardRef, useImperativeHandle } = await import("react");
  return {
    default: forwardRef(function MaskEditor({ image, mask, points, tool, disabled, onPoint, onMaskChange }, ref) {
      useImperativeHandle(ref, () => ({ undo: () => onMaskChange("data:image/png;base64,undone") }));
      return <div data-testid="mask-editor" data-image={image} data-mask={mask || ""} data-points={JSON.stringify(points)} data-tool={tool}>
        <button disabled={disabled} onClick={() => onPoint({ x: 10, y: 10, label: 1 })}>Add point</button>
        <button disabled={disabled} onClick={() => onPoint({ x: 80, y: 40, label: tool === "exclude" ? 0 : 1 })}>Another point</button>
        {(tool === "paint" || tool === "erase") && <button disabled={disabled} onClick={() => onMaskChange("data:image/png;base64,edited")}>Edit mask</button>}
      </div>;
    }),
  };
});

const catalog = [
  { product_id: "chair", name: "Blue chair", category: "armchair", image: "reference" },
  { product_id: "sofa", name: "Green couch", category: "sofa", image: "sofa-reference" },
];
const confidentMask = {
  mask: "mask", mask_review_required: false,
  classification: { category: "chair", label: "chair", confidence: 0.76, uncertain: false },
};
const replacement = { image: "result", elapsed_seconds: 8, seed: 42 };
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const gallerySource = () => localStorage.setItem("selectedImage", JSON.stringify({ image_base64: "fixture", prompt: "old source prompt" }));
const mockService = ({ products = catalog, segmentation = confidentMask, jobResponse } = {}) => {
  axios.post.mockImplementation(url => Promise.resolve({ data: { job_id: url.endsWith("segment") ? "mask-job" : "replace-job" } }));
  axios.get.mockImplementation(url => {
    if (url.includes("/jobs/")) return jobResponse ? jobResponse(url) : Promise.resolve({ data: {
      status: "done", result: url.endsWith("mask-job") ? segmentation : replacement,
    } });
    return Promise.resolve({ data: url.endsWith("products") ? { products } : { status: "ok" } });
  });
};
const renderGallery = async () => {
  gallerySource();
  const view = render(<FurnitureReplace />);
  await screen.findByText("Service ready");
  return view;
};
const selectFurniture = async () => {
  await userEvent.click(screen.getByRole("button", { name: "Add point" }));
  await screen.findByText("Ready", { exact: true });
  await waitFor(() => expect(screen.getByRole("button", { name: "Correct mask" })).toBeEnabled());
};
const expectAuthenticated = () => expect.objectContaining({
  headers: { Authorization: "Bearer test-token" }, signal: expect.any(AbortSignal),
});

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.setItem("token", "test-token");
  mockService();
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

describe("Furniture Replace", () => {
  it("segments on one click and enables a catalog replacement without mask acceptance", async () => {
    localStorage.setItem("selectedImage", JSON.stringify({ image_base64: "fixture", prompt: "old source prompt" }));
    axios.post.mockResolvedValue({ data: { job_id: "mask-job" } });
    axios.get.mockImplementation(url => Promise.resolve({ data: url.includes("/jobs/")
      ? { status: "done", result: { mask: "mask", mask_review_required: false, classification: { category: "chair", label: "chair", confidence: 0.76, uncertain: false } } }
      : url.endsWith("products") ? { products: [{ product_id: "chair", name: "Blue chair", category: "armchair", image: "reference" }] } : { status: "ok" } }));
    render(<FurnitureReplace />);
    await screen.findByText("Service ready");
    await userEvent.click(screen.getByRole("button", { name: "Add point" }));
    expect(await screen.findByText("Match confidence 76%")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Segment" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept mask" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue("chair");
    await userEvent.click(screen.getByRole("button", { name: /Blue chair/ }));
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeEnabled();
  });
  it("defaults to Catalog with Replace gated and authenticates service requests", async () => {
    render(<FurnitureReplace />);
    expect(screen.getByRole("heading", { name: "Furniture Replace" })).toBeInTheDocument();
    expect(await screen.findByText("Service ready")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Catalog" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Description" })).toHaveAttribute("aria-selected", "false");
    expect(screen.queryByRole("textbox", { name: "Replacement description" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Find similar products" })).toBeDisabled();
    expect(screen.getByText("Advanced settings", { exact: true }).closest("details")).not.toHaveAttribute("open");
    expect(axios.get).toHaveBeenCalledWith("/api/furniture/health", expectAuthenticated());
    expect(axios.get).toHaveBeenCalledWith("/api/furniture/products", expectAuthenticated());
  });

  it("loads a gallery image without using its source prompt as the replacement description", async () => {
    await renderGallery();
    expect(screen.getByTestId("mask-editor")).toHaveAttribute("data-image", "data:image/png;base64,fixture");
    expect(localStorage.getItem("selectedImage")).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Description" }));
    expect(screen.getByRole("textbox", { name: "Replacement description" })).toHaveValue("");
    await selectFurniture();
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Replacement description" }), "An oak chair");
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeEnabled();
  });

  it("uploads a new room photo without carrying a gallery source prompt into replacement", async () => {
    vi.stubGlobal("Image", class {
      naturalWidth = 640;
      naturalHeight = 480;
      set src(value) { queueMicrotask(() => this.onload?.()); }
    });
    await renderGallery();
    const file = new File(["new room"], "room.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("Room photo"), file);
    await waitFor(() => expect(screen.getByTestId("mask-editor")).toHaveAttribute("data-image", "data:image/png;base64,bmV3IHJvb20="));
    await userEvent.click(screen.getByRole("tab", { name: "Description" }));
    expect(screen.getByRole("textbox", { name: "Replacement description" })).toHaveValue("");
    await selectFurniture();
    expect(axios.post).toHaveBeenCalledWith("/api/furniture/segment", {
      image: "bmV3IHJvb20=", points: [{ x: 10, y: 10, label: 1 }],
    }, expectAuthenticated());
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
  });

  it("shows service failure without enabling generation", async () => {
    axios.get.mockRejectedValue(new Error("offline"));
    render(<FurnitureReplace />);
    expect(await screen.findByText("Service unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Find similar products" })).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("supports an accessible fixed seed control", async () => {
    await renderGallery();
    await selectFurniture();
    await userEvent.click(screen.getByRole("button", { name: /Blue chair/ }));
    await userEvent.click(screen.getByText("Advanced settings", { exact: true }));
    expect(screen.getByRole("spinbutton", { name: "Seed" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "Random seed" }));
    expect(screen.getByRole("spinbutton", { name: "Seed" })).toBeEnabled();
    await userEvent.clear(screen.getByRole("spinbutton", { name: "Seed" }));
    await userEvent.type(screen.getByRole("spinbutton", { name: "Seed" }), "42");
    await userEvent.click(screen.getByRole("button", { name: "Replace", exact: true }));
    await screen.findByAltText("Replacement result");
    expect(axios.post).toHaveBeenCalledWith("/api/furniture/replace", expect.objectContaining({ seed: 42 }), expectAuthenticated());
  });

  it.each([
    ["armchair", "chairs", "chair"],
    ["couch", "sofas", "sofa"],
    ["tables", "table", "table"],
    ["bookshelf", "shelving", "shelf"],
    ["wardrobe", "dresser", "cabinet"],
    ["beds", "bed", "bed"],
  ])("normalizes confident %s classification and %s catalog aliases to %s", async (detected, category, normalized) => {
    mockService({ products: [
      { product_id: "alias", name: "Matching furniture", category: ` ${category.toUpperCase()} `, image: "reference" },
      { product_id: "other", name: "Other furniture", category: "lamp", image: "other" },
    ], segmentation: { ...confidentMask, classification: { ...confidentMask.classification, category: ` ${detected.toUpperCase()} ` } } });
    await renderGallery();
    await selectFurniture();
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue(normalized);
    expect(screen.getByRole("button", { name: /Matching furniture/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Other furniture/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept mask" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Matching furniture/ }));
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeEnabled();
    expect(axios.post).toHaveBeenCalledTimes(1);
    expect(axios.post).toHaveBeenCalledWith("/api/furniture/segment", {
      image: "fixture", points: [{ x: 10, y: 10, label: 1 }],
    }, expectAuthenticated());
  });

  it("keeps all categories for uncertain classification and requires mask review", async () => {
    mockService({ segmentation: { ...confidentMask, mask_review_required: true,
      classification: { category: "chair", label: "chair", confidence: 0.22, uncertain: true },
    } });
    await renderGallery();
    await userEvent.click(screen.getByRole("button", { name: "Add point" }));
    await screen.findByText("Unknown furniture");
    expect(screen.getByText("Match confidence 22%")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue("all");
    expect(screen.getByRole("button", { name: /Blue chair/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Green couch/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Blue chair/ }));
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Find similar products" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Accept mask" }));
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Find similar products" })).toBeEnabled();
  });

  it.each([
    ["legacy response", { mask: "mask" }],
    ["explicit review", { ...confidentMask, mask_review_required: true }],
    ["string false", { ...confidentMask, mask_review_required: "false" }],
    ["null review flag", { ...confidentMask, mask_review_required: null }],
  ])("does not automatically accept a %s", async (name, segmentation) => {
    mockService({ segmentation });
    await renderGallery();
    await userEvent.click(screen.getByRole("button", { name: "Add point" }));
    await screen.findByText("Mask review required");
    await userEvent.click(screen.getByRole("button", { name: /Blue chair/ }));
    expect(screen.queryByText("Ready", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Accept mask" }));
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeEnabled();
  });

  it("does not filter an unknown classification even without an uncertainty flag", async () => {
    mockService({ segmentation: { ...confidentMask, classification: { category: "unknown", uncertain: false } } });
    await renderGallery();
    await selectFurniture();
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue("all");
    expect(screen.getByRole("button", { name: /Green couch/ })).toBeInTheDocument();
  });

  it.each([undefined, false])("does not filter uncertain classification when review is %s", async review => {
    mockService({ segmentation: { ...confidentMask, mask_review_required: review,
      classification: { ...confidentMask.classification, uncertain: true },
    } });
    await renderGallery();
    await userEvent.click(screen.getByRole("button", { name: "Add point" }));
    await screen.findByText("Unknown furniture");
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue("all");
    expect(screen.getByRole("button", { name: /Green couch/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Green couch/ }));
    if (review === false) expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeEnabled();
    else expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
  });

  it("renders catalog names as text in the default reference controls", async () => {
    mockService({ products: [{ product_id: "chair", name: "<b>Chair</b>", image: "fixture" }] });
    render(<FurnitureReplace />);
    expect(await screen.findByText("<b>Chair</b>")).toBeInTheDocument();
    expect(screen.queryByText("Chair", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find similar products" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
  });

  it.each(["  BLUE  ", "aRmChAiR"])("searches catalog names and categories case-insensitively for %s", async query => {
    render(<FurnitureReplace />);
    await screen.findByRole("button", { name: /Blue chair/ });
    await userEvent.type(screen.getByRole("searchbox", { name: "Search catalog" }), query);
    expect(screen.getByRole("button", { name: /Blue chair/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Green couch/ })).not.toBeInTheDocument();
    await userEvent.clear(screen.getByRole("searchbox", { name: "Search catalog" }));
    expect(screen.getByRole("button", { name: /Green couch/ })).toBeInTheDocument();
  });

  it("offers an all-categories fallback when classification has no matching catalog products", async () => {
    mockService({ products: [catalog[1]] });
    await renderGallery();
    await selectFurniture();
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue("chair");
    expect(screen.getByText("No matching products")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "All categories" }));
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue("all");
    expect(screen.getByRole("button", { name: /Green couch/ })).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search catalog" }), "absent product");
    expect(screen.getByText("No matching products")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "All categories" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Green couch/ })).not.toBeInTheDocument();
  });

  it("preserves the search when all-categories fallback reveals products hidden by classification", async () => {
    await renderGallery();
    await selectFurniture();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search catalog" }), "gReEn");
    expect(screen.getByText("No matching products")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Green couch/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "All categories" }));
    expect(screen.getByRole("searchbox", { name: "Search catalog" })).toHaveValue("gReEn");
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue("all");
    expect(screen.getByRole("button", { name: /Green couch/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Blue chair/ })).not.toBeInTheDocument();
    expect(screen.queryByText("No matching products")).not.toBeInTheDocument();
  });

  it("replaces foreground points on reselection and appends points only while correcting", async () => {
    await renderGallery();
    await selectFurniture();
    await userEvent.click(screen.getByRole("button", { name: "Another point" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Correct mask" })).toBeEnabled());
    expect(axios.post).toHaveBeenNthCalledWith(2, "/api/furniture/segment", {
      image: "fixture", points: [{ x: 80, y: 40, label: 1 }],
    }, expectAuthenticated());
    await userEvent.click(screen.getByRole("button", { name: "Correct mask" }));
    await userEvent.click(screen.getByRole("button", { name: "Add point" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Exclude point" })).toBeEnabled());
    expect(axios.post).toHaveBeenNthCalledWith(3, "/api/furniture/segment", {
      image: "fixture", points: [{ x: 80, y: 40, label: 1 }, { x: 10, y: 10, label: 1 }],
    }, expectAuthenticated());
    await userEvent.click(screen.getByRole("button", { name: "Exclude point" }));
    await userEvent.click(screen.getByRole("button", { name: "Another point" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Select furniture" })).toBeEnabled());
    expect(axios.post).toHaveBeenNthCalledWith(4, "/api/furniture/segment", {
      image: "fixture", points: [{ x: 80, y: 40, label: 1 }, { x: 10, y: 10, label: 1 }, { x: 80, y: 40, label: 0 }],
    }, expectAuthenticated());
    await userEvent.click(screen.getByRole("button", { name: "Select furniture" }));
    await userEvent.click(screen.getByRole("button", { name: "Another point" }));
    await screen.findByText("Ready", { exact: true });
    expect(axios.post).toHaveBeenNthCalledWith(5, "/api/furniture/segment", {
      image: "fixture", points: [{ x: 80, y: 40, label: 1 }],
    }, expectAuthenticated());
    expect(screen.getByTestId("mask-editor")).toHaveAttribute("data-points", JSON.stringify([{ x: 80, y: 40, label: 1 }]));
  });

  it("progressively reveals correction tools and brush controls", async () => {
    await renderGallery();
    expect(screen.getByRole("button", { name: "Correct mask" })).toBeDisabled();
    expect(screen.queryByRole("toolbar", { name: "Mask correction" })).not.toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: "Brush size" })).not.toBeInTheDocument();
    await selectFurniture();
    await userEvent.click(screen.getByRole("button", { name: "Correct mask" }));
    const toolbar = screen.getByRole("toolbar", { name: "Mask correction" });
    for (const name of ["Include point", "Exclude point", "Paint mask", "Erase mask", "Undo"]) {
      expect(within(toolbar).getByRole("button", { name })).toBeEnabled();
    }
    expect(screen.getByTestId("mask-editor")).toHaveAttribute("data-tool", "include");
    expect(screen.queryByRole("slider", { name: "Brush size" })).not.toBeInTheDocument();
    await userEvent.click(within(toolbar).getByRole("button", { name: "Paint mask" }));
    expect(screen.getByTestId("mask-editor")).toHaveAttribute("data-tool", "paint");
    expect(screen.getByRole("slider", { name: "Brush size" })).toHaveValue("24");
    await userEvent.click(within(toolbar).getByRole("button", { name: "Erase mask" }));
    expect(screen.getByTestId("mask-editor")).toHaveAttribute("data-tool", "erase");
    expect(screen.getByRole("slider", { name: "Brush size" })).toBeInTheDocument();
    await userEvent.click(within(toolbar).getByRole("button", { name: "Exclude point" }));
    expect(screen.queryByRole("slider", { name: "Brush size" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Correct mask" }));
    expect(screen.queryByRole("toolbar", { name: "Mask correction" })).not.toBeInTheDocument();
    expect(screen.getByTestId("mask-editor")).toHaveAttribute("data-tool", "select");
  });

  it("invalidates the previous selection and result while reselection is pending", async () => {
    await renderGallery();
    await selectFurniture();
    await userEvent.click(screen.getByRole("button", { name: /Blue chair/ }));
    await userEvent.click(screen.getByRole("button", { name: "Replace", exact: true }));
    await screen.findByAltText("Replacement result");
    await userEvent.click(screen.getByRole("tab", { name: "original", exact: true }));
    const nextMask = deferred();
    axios.get.mockReturnValueOnce(nextMask.promise);
    await userEvent.click(screen.getByRole("button", { name: "Another point" }));
    expect(screen.getByTestId("mask-editor")).toHaveAttribute("data-mask", "");
    expect(screen.queryByAltText("Replacement result")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save to gallery" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Match confidence/)).not.toBeInTheDocument();
    expect(screen.queryByText("Ready", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue("all");
    expect(screen.getByRole("button", { name: /Green couch/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Correct mask" })).toBeDisabled();
    expect(axios.post).toHaveBeenLastCalledWith("/api/furniture/segment", {
      image: "fixture", points: [{ x: 80, y: 40, label: 1 }],
    }, expectAuthenticated());
    await act(async () => { nextMask.resolve({ data: { status: "done", result: { mask: "new-mask", mask_review_required: true } } }); });
    expect(screen.getByTestId("mask-editor")).toHaveAttribute("data-mask", "data:image/png;base64,new-mask");
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Accept mask" }));
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeEnabled();
  });

  it("returns completed jobs and surfaces inference failures", async () => {
    const signal = new AbortController().signal;
    axios.get.mockResolvedValueOnce({ data: { status: "done", result: { image: "result" } } });
    expect(await waitForFurnitureJob("job", signal, vi.fn())).toEqual({ image: "result" });
    expect(axios.get).toHaveBeenCalledWith("/api/furniture/jobs/job", expectAuthenticated());
    axios.get.mockResolvedValueOnce({ data: { status: "failed", error: "GPU busy" } });
    await expect(waitForFurnitureJob("job", signal, vi.fn())).rejects.toThrow("GPU busy");
  });

  it("reports the actual job stage and falls back to status only when stage is absent", async () => {
    vi.useFakeTimers();
    axios.get.mockResolvedValueOnce({ data: { status: "running", stage: "classifying" } })
      .mockResolvedValueOnce({ data: { status: "running" } })
      .mockResolvedValueOnce({ data: { status: "done", stage: "saving", result: replacement } });
    const onStatus = vi.fn();
    const job = waitForFurnitureJob("job", new AbortController().signal, onStatus);
    await vi.advanceTimersByTimeAsync(1400);
    expect(await job).toEqual(replacement);
    expect(onStatus.mock.calls).toEqual([["classifying"], ["running"], ["saving"]]);
    expect(axios.get).toHaveBeenCalledTimes(3);
  });

  it("rejects an aborted late completed response instead of returning its result", async () => {
    const response = deferred();
    axios.get.mockReturnValueOnce(response.promise);
    const controller = new AbortController();
    const job = waitForFurnitureJob("job", controller.signal, vi.fn());
    const rejected = expect(job).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    response.resolve({ data: { status: "done", result: replacement } });
    await rejected;
  });

  it("stops polling immediately when aborted during the polling delay", async () => {
    vi.useFakeTimers();
    axios.get.mockResolvedValueOnce({ data: { status: "running", stage: "generating" } });
    const controller = new AbortController();
    const job = waitForFurnitureJob("job", controller.signal, vi.fn());
    const rejected = expect(job).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    await rejected;
    expect(axios.get).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not commit a late replacement result after the workflow unmounts", async () => {
    const lateResponse = deferred();
    mockService({ jobResponse: url => url.endsWith("mask-job")
      ? Promise.resolve({ data: { status: "done", result: confidentMask } }) : lateResponse.promise });
    const view = await renderGallery();
    await selectFurniture();
    await userEvent.click(screen.getByRole("button", { name: /Blue chair/ }));
    await userEvent.click(screen.getByRole("button", { name: "Replace", exact: true }));
    await waitFor(() => expect(axios.get).toHaveBeenCalledWith("/api/furniture/jobs/replace-job", expectAuthenticated()));
    const request = axios.get.mock.calls.find(([url]) => url.endsWith("replace-job"))[1];
    view.unmount();
    expect(request.signal.aborted).toBe(true);
    await act(async () => { lateResponse.resolve({ data: { status: "done", result: replacement } }); });
    render(<FurnitureReplace />);
    await screen.findByText("Service ready");
    expect(screen.queryByAltText("Replacement result")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save to gallery" })).not.toBeInTheDocument();
  });

  it.each([["classifying", "Recognizing furniture"], ["loading", "Loading model"]])("shows the %s stage with elapsed time and no percentage progress", async (stage, label) => {
    const lateResponse = deferred();
    mockService({ jobResponse: () => lateResponse.promise });
    await renderGallery();
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add point" })); });
    expect(screen.getByRole("status")).toHaveTextContent("Queued");
    expect(screen.getByRole("status")).toHaveTextContent("0s elapsed");
    await act(async () => {
      lateResponse.resolve({ data: { status: "running", stage } });
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByRole("status")).toHaveTextContent(label);
    expect(screen.getByRole("status")).toHaveTextContent("3s elapsed");
    expect(screen.getByRole("status")).not.toHaveTextContent(/%/);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
    cleanup();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["Paint mask", "Erase mask", "Undo"])("clears results, classification, and filtering after %s and requires acceptance", async tool => {
    await renderGallery();
    await selectFurniture();
    await userEvent.click(screen.getByRole("button", { name: /Blue chair/ }));
    await userEvent.click(screen.getByRole("button", { name: "Replace", exact: true }));
    expect(await screen.findByAltText("Replacement result")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save to gallery" })).toBeEnabled();
    expect(screen.getByRole("link", { name: "Download" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Correct mask" }));
    await userEvent.click(screen.getByRole("button", { name: tool === "Undo" ? "Paint mask" : tool }));
    await userEvent.click(screen.getByRole("button", { name: tool === "Undo" ? "Undo" : "Edit mask" }));
    expect(screen.queryByAltText("Replacement result")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save to gallery" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "Image comparison" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Match confidence/)).not.toBeInTheDocument();
    expect(screen.queryByText("Ready", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("Selected furniture", { exact: true })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Catalog category" })).toHaveValue("all");
    expect(screen.getByRole("button", { name: /Green couch/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find similar products" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Accept mask" }));
    expect(screen.getByRole("button", { name: "Replace", exact: true })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Replace", exact: true }));
    await screen.findByAltText("Replacement result");
    expect(axios.post).toHaveBeenLastCalledWith("/api/furniture/replace", expect.objectContaining({
      mask: tool === "Undo" ? "undone" : "edited", mask_job_id: "mask-job",
    }), expectAuthenticated());
  });

  it("does not send an old prompt or Quality profile with a catalog reference", async () => {
    await renderGallery();
    await selectFurniture();
    await userEvent.click(screen.getByRole("tab", { name: "Description" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Replacement description" }), "A stale red chair");
    await userEvent.click(screen.getByText("Advanced settings", { exact: true }));
    await userEvent.click(screen.getByRole("button", { name: "quality", exact: true }));
    expect(screen.getByRole("button", { name: "quality", exact: true })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Catalog" }));
    expect(screen.queryByRole("button", { name: "quality", exact: true })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Blue chair/ }));
    await userEvent.click(screen.getByRole("button", { name: "Replace", exact: true }));
    await screen.findByAltText("Replacement result");
    expect(axios.post).toHaveBeenCalledWith("/api/furniture/replace", expect.objectContaining({
      mode: "reference", product_id: "chair", quality: "balanced", prompt: undefined,
    }), expectAuthenticated());
    await userEvent.click(screen.getByRole("tab", { name: "Description" }));
    expect(screen.getByRole("button", { name: "balanced", exact: true })).toHaveAttribute("aria-pressed", "true");
  });
});