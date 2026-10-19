import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPanoramaExport, downloadPanorama } from "../src/views/workflows/panorama-360/panoramaExport";

function readBlob(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result));
    reader.onerror = reject;
    reader.readAsArrayBuffer(blob);
  });
}

describe("panorama export", () => {
  let decode;
  let imageSize;
  let context;
  let toBlob;

  beforeEach(() => {
    decode = vi.fn().mockResolvedValue(undefined);
    imageSize = { width: 1024, height: 512 };
    vi.stubGlobal("Image", class {
      get naturalWidth() { return imageSize.width; }
      get naturalHeight() { return imageSize.height; }
      decode() { return decode(); }
    });
    context = { fillRect: vi.fn(), drawImage: vi.fn() };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context);
    toBlob = vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(callback => callback({
      arrayBuffer: async () => new Uint8Array([0xff, 0xd8, 0xff, 0xd9]).buffer,
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("preserves the original PNG bytes without resampling", async () => {
    const original = "original PNG bytes";
    const result = await createPanoramaExport(btoa(original), "png");
    expect(result.filename).toBe("ainterior-panorama-360.png");
    expect(result.blob.type).toBe("image/png");
    expect(new TextDecoder().decode(await readBlob(result.blob))).toBe(original);
    expect(toBlob).not.toHaveBeenCalled();
  });

  it("writes a JPEG APP1 packet with valid GPano XML and actual image dimensions", async () => {
    imageSize = { width: 2048, height: 1024 };
    const result = await createPanoramaExport("unused", "jpeg");
    expect(result.filename).toBe("ainterior-panorama-360.jpg");
    expect(result.blob.type).toBe("image/jpeg");
    expect(toBlob).toHaveBeenCalledWith(expect.any(Function), "image/jpeg", 0.95);
    const canvas = toBlob.mock.instances[0];
    expect([canvas.width, canvas.height]).toEqual([2048, 1024]);
    const bytes = await readBlob(result.blob);
    expect([...bytes.subarray(0, 4)]).toEqual([0xff, 0xd8, 0xff, 0xe1]);
    const packetLength = (bytes[4] << 8) | bytes[5];
    const packet = new TextDecoder().decode(bytes.subarray(6, 4 + packetLength));
    const prefix = "http://ns.adobe.com/xap/1.0/\0";
    expect(packet.startsWith(prefix)).toBe(true);
    const xml = new DOMParser().parseFromString(packet.slice(prefix.length), "application/xml");
    expect(xml.querySelector("parsererror")).toBeNull();
    const description = xml.getElementsByTagNameNS("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "Description")[0];
    const property = name => description.getAttributeNS("http://ns.google.com/photos/1.0/panorama/", name);
    expect(property("ProjectionType")).toBe("equirectangular");
    expect(property("UsePanoramaViewer")).toBe("True");
    expect(property("FullPanoWidthPixels")).toBe("2048");
    expect(property("FullPanoHeightPixels")).toBe("1024");
    expect(property("CroppedAreaImageWidthPixels")).toBe("2048");
    expect(property("CroppedAreaImageHeightPixels")).toBe("1024");
    expect(property("CroppedAreaLeftPixels")).toBe("0");
    expect(property("CroppedAreaTopPixels")).toBe("0");
    expect([...bytes.subarray(4 + packetLength)]).toEqual([0xff, 0xd9]);
  });

  it("rejects unsupported formats", async () => {
    await expect(createPanoramaExport("unused", "mp4")).rejects.toThrow("Unsupported");
    expect(decode).not.toHaveBeenCalled();
  });

  it.each([{ width: 1000, height: 1000 }, { width: 0, height: 0 }])("rejects invalid panorama dimensions: %j", async size => {
    imageSize = size;
    await expect(createPanoramaExport("unused", "jpeg")).rejects.toThrow("2:1");
    expect(toBlob).not.toHaveBeenCalled();
  });

  it("reports a corrupt image", async () => {
    decode.mockRejectedValueOnce(new Error("Image decode failed"));
    await expect(createPanoramaExport("unused", "png")).rejects.toThrow("decode");
  });

  it("reports unavailable canvas support", async () => {
    HTMLCanvasElement.prototype.getContext.mockReturnValueOnce(null);
    await expect(createPanoramaExport("unused", "jpeg")).rejects.toThrow("unavailable");
  });

  it("reports an encoder failure", async () => {
    toBlob.mockImplementationOnce(callback => callback(null));
    await expect(createPanoramaExport("unused", "jpeg")).rejects.toThrow("could not export");
  });

  it("rejects an unexpected encoder format", async () => {
    toBlob.mockImplementationOnce(callback => callback({ arrayBuffer: async () => new Uint8Array([1, 2]).buffer }));
    await expect(createPanoramaExport("unused", "jpeg")).rejects.toThrow("valid JPEG");
  });

  it("downloads the file and releases its temporary link and URL", async () => {
    vi.useFakeTimers();
    const createObjectURL = vi.fn().mockReturnValue("blob:panorama");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
      expect(this.download).toBe("ainterior-panorama-360.png");
      expect(this.href).toBe("blob:panorama");
      expect(this.isConnected).toBe(true);
    });
    await downloadPanorama(btoa("image"), "png");
    expect(click).toHaveBeenCalledOnce();
    expect(document.querySelector("a[download]")).toBeNull();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:panorama");
  });
});