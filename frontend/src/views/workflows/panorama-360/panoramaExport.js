const GPANO_NAMESPACE = "http://ns.google.com/photos/1.0/panorama/";
const RDF_NAMESPACE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#";

async function addPanoramaMetadata(jpeg, width, height) {
  const metadata = document.implementation.createDocument("adobe:ns:meta/", "x:xmpmeta");
  const rdf = metadata.createElementNS(RDF_NAMESPACE, "rdf:RDF");
  const description = metadata.createElementNS(RDF_NAMESPACE, "rdf:Description");
  description.setAttributeNS(RDF_NAMESPACE, "rdf:about", "");
  const properties = {
    ProjectionType: "equirectangular",
    UsePanoramaViewer: "True",
    FullPanoWidthPixels: width,
    FullPanoHeightPixels: height,
    CroppedAreaImageWidthPixels: width,
    CroppedAreaImageHeightPixels: height,
    CroppedAreaLeftPixels: 0,
    CroppedAreaTopPixels: 0,
  };
  for (const [name, value] of Object.entries(properties)) {
    description.setAttributeNS(GPANO_NAMESPACE, `GPano:${name}`, String(value));
  }
  rdf.appendChild(description);
  metadata.documentElement.appendChild(rdf);
  const packet = new TextEncoder().encode(
    `http://ns.adobe.com/xap/1.0/\0${new XMLSerializer().serializeToString(metadata)}`
  );
  const bytes = new Uint8Array(await jpeg.arrayBuffer());
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) {
    throw new Error("The browser did not produce a valid JPEG image.");
  }
  const length = packet.length + 2;
  return new Blob([
    bytes.subarray(0, 2),
    new Uint8Array([0xff, 0xe1, length >> 8, length & 0xff]),
    packet,
    bytes.subarray(2),
  ], { type: "image/jpeg" });
}

export async function createPanoramaExport(imageBase64, format) {
  if (format !== "png" && format !== "jpeg") {
    throw new Error("Unsupported panorama format.");
  }
  const image = new Image();
  image.src = `data:image/png;base64,${imageBase64}`;
  await image.decode();
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  if (!width || !height || width !== height * 2) {
    throw new Error("VR export requires a full 2:1 equirectangular panorama.");
  }
  if (format === "png") {
    const bytes = Uint8Array.from(atob(imageBase64), character => character.charCodeAt(0));
    return { blob: new Blob([bytes], { type: "image/png" }), filename: "ainterior-panorama-360.png" };
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Image export is unavailable in this browser.");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0);
  const jpeg = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.95));
  if (!jpeg) throw new Error("The browser could not export this panorama.");
  return {
    blob: await addPanoramaMetadata(jpeg, width, height),
    filename: "ainterior-panorama-360.jpg",
  };
}

export async function downloadPanorama(imageBase64, format) {
  const { blob, filename } = await createPanoramaExport(imageBase64, format);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  try {
    link.click();
  } finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}