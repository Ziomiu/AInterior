import { useState } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { LuDownload, LuLoaderCircle } from "react-icons/lu";

import { toaster } from "../../../components/ui/toaster";
import Button from "../../../components/ui/Button";
import Card from "../../../components/ui/Card";
import PanoramaViewer from "./PanoramaViewer";
import { downloadPanorama } from "./panoramaExport";

const DEFAULT_BRIEF = "A multifunctional exhibition space with a clear circulation loop, flexible display zones, adjustable glare-free lighting, high-contrast wayfinding, quiet sensory retreat, tactile materials, step-free access, generous turning space, and seating with varied visual and acoustic comfort";
const PANORAMA_INSTRUCTIONS = "seamless equirectangular 360-degree architectural panorama, 2:1 horizontal composition, continuous horizon, coherent connected exhibition interior, immersive environment visualization, no frame, no labels, no text";
const NEGATIVE_PROMPT = "watermark, text, border, collage, split image, fisheye closeup, duplicated furniture, blocked circulation, inaccessible stairs";

export default function Panorama360() {
  const [brief, setBrief] = useState(DEFAULT_BRIEF);
  const [image, setImage] = useState("");
  const [loading, setLoading] = useState(false);
  const [flatView, setFlatView] = useState(false);
  const [downloadFormat, setDownloadFormat] = useState("jpeg");
  const [exporting, setExporting] = useState(false);

  const download = async () => {
    setExporting(true);
    try {
      await downloadPanorama(image, downloadFormat);
    } catch (error) {
      toaster.create({
        title: "Panorama download failed",
        description: error.message || "Could not export the panorama.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    } finally {
      setExporting(false);
    }
  };

  const generate = async () => {
    const token = localStorage.getItem("token");
    if (!token) {
      toaster.create({
        title: "Not logged in",
        description: "You must be logged in to generate images.",
        status: "warning",
        duration: 3000,
        isClosable: true,
      });
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(
        "/api/model/generate/text-to-image",
        {
          model_version: "xl",
          prompt: `${brief.trim()}, ${PANORAMA_INSTRUCTIONS}`,
          negative_prompt: NEGATIVE_PROMPT,
          guidance_scale: 7,
          width: 1024,
          height: 512,
          seed: Math.floor(Math.random() * 999999999),
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setImage(response.data.image);
      setFlatView(false);
    } catch (error) {
      toaster.create({
        title: "Panorama generation failed",
        description: error.response?.data?.detail || "Something went wrong.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-4">
      <Card className="w-full max-w-[1600px] grid grid-cols-1 xl:grid-cols-[minmax(300px,0.8fr)_minmax(0,1.2fr)] gap-6 p-5">
        <section className="flex flex-col gap-4">
          <div>
            <p className="text-xs font-semibold uppercase text-accent">Immersive workflow</p>
            <h1 className="font-bold text-3xl">360 Image</h1>
          </div>
          <label htmlFor="panorama-brief" className="font-medium">Exhibition space brief</label>
          <textarea
            id="panorama-brief"
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            maxLength={1500}
            rows={8}
            className="w-full resize-y rounded-md border border-foreground/20 bg-background p-3 text-foreground focus:outline-2 focus:outline-accent"
          />
          <p className="text-sm text-muted">AI-generated panorama for early spatial exploration. Review the image seam and accessibility decisions in your design model.</p>
          <Button
            variant="accent"
            onClick={generate}
            disabled={loading || exporting || !brief.trim()}
            className="mt-auto w-full normal-case tracking-normal"
          >
            {loading ? "Generating panorama..." : "Generate 360 image"}
          </Button>
          {image && <Link to="/views/gallery" className="text-center text-sm text-accent underline">Open gallery</Link>}
        </section>

        <section className="flex min-h-[320px] flex-col gap-3" aria-label="Panorama preview">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-semibold">Preview</h2>
            {image && (
              <div className="flex gap-2" role="group" aria-label="Preview mode">
                <button type="button" onClick={() => setFlatView(false)} aria-pressed={!flatView} className={`rounded px-3 py-1 text-sm ${!flatView ? "bg-primary text-primary-foreground" : "border border-foreground/20"}`}>360 view</button>
                <button type="button" onClick={() => setFlatView(true)} aria-pressed={flatView} className={`rounded px-3 py-1 text-sm ${flatView ? "bg-primary text-primary-foreground" : "border border-foreground/20"}`}>Flat image</button>
              </div>
            )}
          </div>
          <div className="relative min-h-[300px] flex-1 overflow-hidden rounded-md bg-[#171a18]">
            {loading ? (
              <div className="absolute inset-0 grid place-items-center text-white/80" role="status">Generating panorama...</div>
            ) : image ? (
              flatView ? (
                <img src={`data:image/png;base64,${image}`} alt="Generated equirectangular exhibition-space panorama" className="h-full min-h-[300px] w-full object-contain" />
              ) : (
                <PanoramaViewer imageBase64={image} />
              )
            ) : (
              <div className="absolute inset-0 grid place-items-center text-white/70">Your panorama will appear here</div>
            )}
          </div>
          {image && (
            <div className="flex items-center justify-end gap-2" role="group" aria-label="Panorama download">
              <select
                aria-label="Download format"
                value={downloadFormat}
                onChange={event => setDownloadFormat(event.target.value)}
                disabled={loading || exporting}
                className="min-w-0 max-w-full rounded border border-foreground/20 bg-background px-2 py-2 text-sm disabled:opacity-50"
              >
                <option value="jpeg">JPEG (360 metadata)</option>
                <option value="png">PNG (lossless)</option>
              </select>
              <button
                type="button"
                onClick={download}
                disabled={loading || exporting}
                aria-label="Download panorama"
                aria-busy={exporting}
                title={exporting ? "Exporting panorama" : "Download panorama"}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded border border-foreground/20 hover:bg-foreground/5 disabled:opacity-50"
              >
                {exporting ? <LuLoaderCircle className="animate-spin" aria-hidden="true" /> : <LuDownload aria-hidden="true" />}
              </button>
            </div>
          )}
        </section>
      </Card>
    </div>
  );
}