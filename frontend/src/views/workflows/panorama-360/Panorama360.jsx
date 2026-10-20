import { useEffect, useState } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { LuDownload, LuLoaderCircle, LuRefreshCw, LuShuffle } from "react-icons/lu";

import { toaster } from "../../../components/ui/toaster";
import Button from "../../../components/ui/Button";
import Card from "../../../components/ui/Card";
import PanoramaViewer from "./PanoramaViewer";
import { downloadPanorama } from "./panoramaExport";

const DEFAULT_BRIEF = "A multifunctional exhibition space with a clear circulation loop, flexible display zones, adjustable glare-free lighting, high-contrast wayfinding, quiet sensory retreat, tactile materials, step-free access, generous turning space, and seating with varied visual and acoustic comfort";
const NEGATIVE_PROMPT = "watermark, text, border, collage, split image, fisheye closeup, duplicated furniture, blocked circulation, inaccessible stairs";

export default function Panorama360() {
  const [brief, setBrief] = useState(DEFAULT_BRIEF);
  const [image, setImage] = useState("");
  const [loading, setLoading] = useState(false);
  const [flatView, setFlatView] = useState(false);
  const [downloadFormat, setDownloadFormat] = useState("jpeg");
  const [exporting, setExporting] = useState(false);
  const [models, setModels] = useState([]);
  const [modelId, setModelId] = useState("");
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelError, setModelError] = useState("");
  const [inventoryAttempt, setInventoryAttempt] = useState(0);
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 4294967296));
  const [negativePrompt, setNegativePrompt] = useState(NEGATIVE_PROMPT);
  const [quality, setQuality] = useState("draft");
  const [qualities, setQualities] = useState(["draft"]);
  const [resultSize, setResultSize] = useState("");
  const validSeed = Number.isInteger(Number(seed)) && seed !== "" && Number(seed) >= 0 && Number(seed) <= 4294967295;

  useEffect(() => {
    let active = true;
    setModelsLoading(true);
    setModelError("");
    axios.get("/api/model/panorama/models", {
      headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
    }).then(({ data }) => {
      if (!active) return;
      setModels(data.models);
      const availableQualities = data.qualities || ["draft"];
      setQualities(availableQualities);
      setQuality(previous => availableQualities.includes(previous) ? previous : "draft");
      setModelId(previous => data.models.some(model => model.id === previous) ? previous : data.models[0]?.id || "");
      if (!data.models.length) setModelError("No panorama models are installed on the server.");
    }).catch(() => {
      if (!active) return;
      setModels([]);
      setModelId("");
      setModelError("Could not load panorama models.");
    }).finally(() => {
      if (active) setModelsLoading(false);
    });
    return () => { active = false; };
  }, [inventoryAttempt]);

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
    if (!modelId || !brief.trim() || !validSeed) return;
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
        "/api/model/generate/panorama",
        {
          model_id: modelId,
          brief: brief.trim(),
          negative_prompt: negativePrompt,
          seed: Number(seed),
          quality,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setImage(response.data.image);
      const selectedModel = models.find(model => model.id === modelId);
      setResultSize(quality === "high" ? "4096 x 2048" : selectedModel?.width ? `${selectedModel.width} x ${selectedModel.height}` : "");
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
          <div className="flex flex-col gap-2">
            <label htmlFor="panorama-model" className="font-medium">Model</label>
            <select
              id="panorama-model"
              value={modelId}
              onChange={event => setModelId(event.target.value)}
              disabled={modelsLoading || loading || exporting || !models.length}
              className="w-full min-w-0 rounded-md border border-foreground/20 bg-background p-3 text-foreground disabled:opacity-50"
            >
              {!models.length && <option value="">{modelsLoading ? "Loading models..." : "No models available"}</option>}
              {models.map(model => <option key={model.id} value={model.id}>{model.label}</option>)}
            </select>
            {modelError && (
              <div className="flex items-center justify-between gap-2 text-sm" role="alert">
                <span>{modelError}</span>
                <button type="button" onClick={() => setInventoryAttempt(attempt => attempt + 1)} aria-label="Reload models" title="Reload models" className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded border border-foreground/20">
                  <LuRefreshCw aria-hidden="true" />
                </button>
              </div>
            )}
          </div>
          <fieldset disabled={loading || exporting || modelsLoading} className="flex min-w-0 flex-col gap-2">
            <legend className="mb-2 font-medium">Quality</legend>
            <div className="grid grid-cols-2 gap-2">
              {[{ id: "draft", label: "Draft" }, { id: "high", label: "High / 4K" }].map(option => (
                <label key={option.id} className={`flex min-h-11 items-center gap-2 rounded-md border p-2 text-sm ${quality === option.id ? "border-accent bg-accent/10" : "border-foreground/20"} ${!qualities.includes(option.id) ? "opacity-50" : "cursor-pointer"}`}>
                  <input type="radio" name="panorama-quality" value={option.id} checked={quality === option.id} onChange={() => setQuality(option.id)} disabled={!qualities.includes(option.id)} />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label htmlFor="panorama-brief" className="font-medium">Exhibition space brief</label>
          <textarea
            id="panorama-brief"
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            maxLength={1500}
            rows={8}
            className="w-full resize-y rounded-md border border-foreground/20 bg-background p-3 text-foreground focus:outline-2 focus:outline-accent"
          />
          <div className="flex flex-col gap-2">
            <label htmlFor="panorama-seed" className="font-medium">Seed</label>
            <div className="flex gap-2">
              <input id="panorama-seed" type="number" min="0" max="4294967295" step="1" value={seed} onChange={event => setSeed(event.target.value)} disabled={loading || exporting} aria-invalid={!validSeed} className="min-w-0 flex-1 rounded-md border border-foreground/20 bg-background p-2" />
              <button type="button" onClick={() => setSeed(Math.floor(Math.random() * 4294967296))} disabled={loading || exporting} aria-label="Randomize seed" title="Randomize seed" className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded border border-foreground/20 disabled:opacity-50"><LuShuffle aria-hidden="true" /></button>
            </div>
          </div>
          <label htmlFor="panorama-negative" className="font-medium">Exclude</label>
          <textarea id="panorama-negative" value={negativePrompt} onChange={event => setNegativePrompt(event.target.value)} maxLength={500} rows={2} className="w-full resize-y rounded-md border border-foreground/20 bg-background p-3 text-foreground" />
          <Button
            variant="accent"
            onClick={generate}
            disabled={loading || exporting || modelsLoading || !modelId || !brief.trim() || !validSeed}
            className="mt-auto w-full normal-case tracking-normal"
          >
            {loading ? "Generating panorama..." : "Generate 360 image"}
          </Button>
          {image && <Link to="/views/gallery" className="text-center text-sm text-accent underline">Open gallery</Link>}
        </section>

        <section className="flex min-h-[320px] flex-col gap-3" aria-label="Panorama preview">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-semibold">Preview{image && resultSize ? ` - ${resultSize}` : ""}</h2>
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