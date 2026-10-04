import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { LuCheck, LuDownload, LuEraser, LuImagePlus, LuMinus, LuPaintbrush, LuPlus, LuRefreshCw, LuSave, LuSparkles, LuUndo2, LuX } from "react-icons/lu";
import Button from "../../../components/ui/Button";
import Input from "../../../components/ui/Input";
import FurnitureMaskCanvas from "../../../components/FurnitureMaskCanvas";
import { toaster } from "../../../components/ui/toaster";

const base64 = source => source.split(",")[1];
const options = signal => ({ headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }, signal });

export async function waitForFurnitureJob(jobId, signal, onStatus) {
  const deadline = Date.now() + 600000;
  while (!signal.aborted && Date.now() < deadline) {
    const response = await axios.get(`/api/furniture/jobs/${jobId}`, options(signal));
    onStatus(response.data.status);
    if (response.data.status === "done") return response.data.result;
    if (response.data.status === "failed") throw new Error(response.data.error || "Generation failed");
    await new Promise(resolve => {
      const timer = setTimeout(() => { signal.removeEventListener("abort", stop); resolve(); }, 700);
      const stop = () => { clearTimeout(timer); resolve(); };
      signal.addEventListener("abort", stop, { once: true });
    });
  }
  if (signal.aborted) throw new DOMException("Stopped waiting", "AbortError");
  throw new Error("Stopped waiting after 10 minutes. The server task may still be running.");
}

async function readPhoto(file) {
  if (!file.type.startsWith("image/") || file.size > 5 * 1024 * 1024) throw new Error("Choose an image up to 5 MB");
  const source = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  await new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => maxSize(image) ? reject(new Error("Maximum image side is 4096 pixels")) : resolve();
    image.onerror = () => reject(new Error("Could not load this image"));
    image.src = source;
  });
  return source;
}

const maxSize = image => Math.max(image.naturalWidth, image.naturalHeight) > 4096;

export default function FurnitureReplace() {
  const [photo, setPhoto] = useState(null);
  const [points, setPoints] = useState([]);
  const [mask, setMask] = useState(null);
  const [maskJob, setMaskJob] = useState(null);
  const [accepted, setAccepted] = useState(false);
  const [tool, setTool] = useState("include");
  const [brushSize, setBrushSize] = useState(24);
  const [mode, setMode] = useState("prompt");
  const [quality, setQuality] = useState("balanced");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("blurry, distorted, duplicate furniture, floating furniture, bad perspective");
  const [steps, setSteps] = useState(30);
  const [guidance, setGuidance] = useState(7.5);
  const [growth, setGrowth] = useState(6);
  const [seed, setSeed] = useState(0);
  const [randomSeed, setRandomSeed] = useState(true);
  const [ipScale, setIpScale] = useState(0.85);
  const [products, setProducts] = useState([]);
  const [selected, setSelected] = useState(null);
  const [productPhoto, setProductPhoto] = useState(null);
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("armchair");
  const [result, setResult] = useState(null);
  const [comparison, setComparison] = useState("result");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [available, setAvailable] = useState(null);
  const [saved, setSaved] = useState(false);
  const controllerRef = useRef(null);
  const editorRef = useRef(null);

  const refresh = async signal => {
    try {
      await axios.get("/api/furniture/health", options(signal));
      setAvailable(true);
      const response = await axios.get("/api/furniture/products", options(signal));
      setProducts(response.data.products);
    } catch (failure) {
      if (failure.code !== "ERR_CANCELED") setAvailable(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    const stored = localStorage.getItem("selectedImage");
    if (stored) {
      try {
        const image = JSON.parse(stored);
        if (image.image_base64) setPhoto(`data:image/png;base64,${image.image_base64}`);
        setPrompt(image.prompt || "");
      } catch { setError("Could not load the selected gallery image"); }
      localStorage.removeItem("selectedImage");
    }
    return () => { controller.abort(); controllerRef.current?.abort(); };
  }, []);

  const run = async action => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setBusy(true);
    setError("");
    try { await action(controller.signal); }
    catch (failure) {
      if (failure.name !== "AbortError" && failure.code !== "ERR_CANCELED") {
        const detail = failure.response?.data?.detail;
        setError(typeof detail === "string" ? detail : failure.message || "Request failed");
      }
    } finally {
      if (controllerRef.current === controller) { setBusy(false); setStatus(""); }
    }
  };

  const resetMask = () => { setMask(null); setMaskJob(null); setAccepted(false); setResult(null); setSaved(false); };
  const choosePhoto = async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const source = await readPhoto(file);
      setPhoto(source); setPoints([]); resetMask(); setSelected(null); setError("");
    } catch (failure) { setError(failure.message); }
    event.target.value = "";
  };

  const segment = () => run(async signal => {
    setAccepted(false);
    setStatus("queued");
    const response = await axios.post("/api/furniture/segment", { image: base64(photo), points }, options(signal));
    const outcome = await waitForFurnitureJob(response.data.job_id, signal, setStatus);
    setMask(`data:image/png;base64,${outcome.mask}`);
    setMaskJob(response.data.job_id);
    setResult(null); setSaved(false);
  });

  const match = () => run(async signal => {
    setStatus("Searching catalog");
    const response = await axios.post("/api/furniture/match", {
      image: base64(photo), mask: base64(mask), mask_job_id: maskJob,
    }, options(signal));
    setProducts(response.data.matches); setSelected(null);
  });

  const ingest = () => run(async signal => {
    setStatus("Indexing reference");
    const response = await axios.post("/api/furniture/products", {
      image: base64(productPhoto), name: productName.trim(), category: category.trim(),
    }, options(signal));
    setProducts(previous => [response.data, ...previous]); setSelected(response.data);
    setMode("reference"); setQuality("balanced"); setProductPhoto(null); setProductName("");
  });

  const generate = () => run(async signal => {
    const nextSeed = randomSeed ? Math.floor(Math.random() * 4294967296) : Number(seed);
    setSeed(nextSeed); setResult(null); setSaved(false); setStatus("queued");
    const response = await axios.post("/api/furniture/replace", {
      image: base64(photo), mask: base64(mask), mask_job_id: maskJob, mode,
      prompt: mode === "prompt" ? prompt.trim() : undefined, negative_prompt: negative,
      product_id: mode === "reference" ? selected.product_id : undefined,
      quality: mode === "reference" ? "balanced" : quality, seed: nextSeed,
      steps: Number(steps), guidance_scale: Number(guidance), ip_scale: Number(ipScale), mask_growth: Number(growth),
    }, options(signal));
    const outcome = await waitForFurnitureJob(response.data.job_id, signal, setStatus);
    setResult({ ...outcome, jobId: response.data.job_id }); setComparison("result");
  });

  const save = () => run(async signal => {
    await axios.post(`/api/furniture/jobs/${result.jobId}/save`, {}, options(signal));
    setSaved(true);
    toaster.create({ title: "Saved to gallery", status: "success", duration: 3000 });
  });

  const iconButton = (name, icon, onClick, disabled = false, active = false) => <button type="button" title={name} aria-label={name}
    disabled={busy || disabled} onClick={onClick} className={`w-10 h-10 shrink-0 inline-flex items-center justify-center rounded-sm border transition-colors disabled:opacity-40 ${active ? "bg-accent text-accent-foreground border-accent" : "border-foreground/20 hover:bg-foreground/5"}`}>{icon}</button>;
  const canGenerate = available && photo && mask && maskJob && accepted && (mode === "prompt" ? prompt.trim() : selected);

  return <div className="w-full max-w-[1600px] mx-auto min-h-screen p-5 space-y-6">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-foreground/15 pb-4">
      <h1 className="font-serif text-3xl font-bold">Furniture Replace</h1>
      <div className="flex items-center gap-2 text-sm text-muted">
        <span className={`w-2 h-2 rounded-full ${available ? "bg-accent" : "bg-red-500"}`} />
        <span>{available === null ? "Connecting" : available ? "Service ready" : "Service unavailable"}</span>
        {iconButton("Refresh service", <LuRefreshCw />, () => refresh())}
      </div>
    </header>
    {error && <div role="alert" className="border-l-2 border-red-500 bg-red-500/5 p-3 text-sm">{error}</div>}
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-6">
      <section className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <label className={`inline-flex items-center gap-2 px-4 py-2 border border-foreground/20 rounded-sm text-sm ${busy ? "opacity-40" : "cursor-pointer hover:bg-foreground/5"}`}>
            <LuImagePlus /> Photo
            <input aria-label="Room photo" className="hidden" type="file" accept="image/*" disabled={busy} onChange={choosePhoto} />
          </label>
          {iconButton("Include point", <LuPlus />, () => setTool("include"), !photo, tool === "include")}
          {iconButton("Exclude point", <LuMinus />, () => setTool("exclude"), !photo, tool === "exclude")}
          {iconButton("Paint mask", <LuPaintbrush />, () => setTool("paint"), !mask, tool === "paint")}
          {iconButton("Erase mask", <LuEraser />, () => setTool("erase"), !mask, tool === "erase")}
          {iconButton("Undo", <LuUndo2 />, () => {
            if (tool === "paint" || tool === "erase") editorRef.current?.undo();
            else { setPoints(previous => previous.slice(0, -1)); resetMask(); }
          }, !photo)}
          {iconButton("Clear mask", <LuX />, () => { setPoints([]); resetMask(); }, !photo)}
          {(tool === "paint" || tool === "erase") && <input aria-label="Brush size" type="range" min="4" max="100" value={brushSize} onChange={event => setBrushSize(Number(event.target.value))} className="w-24 accent-accent" />}
        </div>
        <div className="border border-foreground/15 bg-surface min-h-[280px] overflow-hidden rounded-md">
          {photo ? <FurnitureMaskCanvas key={maskJob || "unsegmented"} ref={editorRef} image={photo} mask={mask} points={points} tool={tool} brushSize={brushSize} disabled={busy}
            onPoint={point => { setPoints(previous => [...previous, point].slice(-64)); resetMask(); }}
            onMaskChange={next => { setMask(next); setAccepted(false); }} />
            : <div className="min-h-[400px] flex flex-col items-center justify-center text-muted gap-3"><LuImagePlus size={36} /><span>Room photo</span></div>}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" icon={<LuSparkles />} onClick={segment} disabled={busy || !available || !photo || !points.some(point => point.label)}>Segment</Button>
          <Button variant={accepted ? "accent" : "outline"} icon={<LuCheck />} onClick={() => setAccepted(true)} disabled={busy || !mask || accepted}>{accepted ? "Mask accepted" : "Accept mask"}</Button>
          {busy && <span role="status" className="text-sm text-muted">{status || "Processing"}</span>}
        </div>
        {result && <section className="border-t border-foreground/15 pt-5 space-y-3">
          <div className="flex flex-wrap justify-between items-center gap-3">
            <div role="tablist" aria-label="Image comparison" className="inline-flex border border-foreground/20 rounded-sm">
              {["original", "result"].map(tab => <button role="tab" aria-selected={comparison === tab} key={tab} onClick={() => setComparison(tab)} className={`px-4 py-2 text-sm capitalize ${comparison === tab ? "bg-foreground text-background" : "hover:bg-foreground/5"}`}>{tab}</button>)}
            </div>
            <span className="text-sm text-muted">{result.elapsed_seconds}s · seed {result.seed}</span>
          </div>
          <img src={comparison === "original" ? photo : `data:image/png;base64,${result.image}`} alt={comparison === "original" ? "Original room" : "Replacement result"} className="w-full h-auto border border-foreground/15 rounded-md" />
          <div className="flex gap-3 flex-wrap">
            <Button icon={<LuSave />} onClick={save} disabled={busy || saved}>{saved ? "Saved" : "Save to gallery"}</Button>
            <a href={`data:image/png;base64,${result.image}`} download="furniture-replacement.png" className="inline-flex items-center gap-2 border border-foreground/20 px-4 py-2 rounded-sm text-sm"><LuDownload /> Download</a>
          </div>
        </section>}
      </section>
      <aside className="min-w-0 space-y-5">
        <div role="tablist" aria-label="Replacement mode" className="grid grid-cols-2 border border-foreground/20 rounded-sm">
          {["prompt", "reference"].map(tab => <button role="tab" aria-selected={mode === tab} disabled={busy} key={tab} onClick={() => { setMode(tab); if (tab === "reference") setQuality("balanced"); }} className={`px-3 py-2 text-sm capitalize ${mode === tab ? "bg-foreground text-background" : "hover:bg-foreground/5"}`}>{tab}</button>)}
        </div>
        {mode === "prompt" ? <>
          <label className="block text-sm space-y-2"><span>Prompt</span><textarea value={prompt} onChange={event => setPrompt(event.target.value)} disabled={busy} rows={4} maxLength={2000} className="w-full p-3 rounded-md border border-foreground/15 bg-transparent focus:ring-2 focus:ring-accent outline-none" /></label>
          <fieldset disabled={busy} className="space-y-2"><legend className="text-sm mb-2">Generation profile</legend><div className="flex border border-foreground/20 rounded-sm">
            {["balanced", "quality"].map(profile => <button type="button" key={profile} aria-pressed={quality === profile} onClick={() => setQuality(profile)} className={`flex-1 p-2 text-sm capitalize ${quality === profile ? "bg-accent text-accent-foreground" : "hover:bg-foreground/5"}`}>{profile}</button>)}
          </div></fieldset>
        </> : <>
          <div className="flex justify-between items-center"><h2 className="font-serif text-lg font-semibold">Catalog</h2><Button variant="outline" onClick={match} disabled={busy || !accepted || !available}>Find matches</Button></div>
          <div className="grid grid-cols-2 gap-3 max-h-[420px] overflow-y-auto">
            {products.map(product => <button type="button" key={product.product_id} disabled={busy} onClick={() => setSelected(product)} aria-pressed={selected?.product_id === product.product_id}
              className={`text-left border rounded-md overflow-hidden ${selected?.product_id === product.product_id ? "border-accent ring-1 ring-accent" : "border-foreground/15"}`}>
              <img src={`data:image/png;base64,${product.image}`} alt={product.name} className="w-full aspect-square object-contain bg-surface" />
              <span className="block p-2 text-sm break-words">{product.name}</span>
            </button>)}
          </div>
          {!products.length && <p className="text-sm text-muted">No catalog products</p>}
          <details className="border-y border-foreground/15 py-3"><summary className="cursor-pointer text-sm">Add reference</summary><div className="space-y-3 pt-3">
            <input aria-label="Reference photo" type="file" accept="image/*" disabled={busy} className="w-full text-sm" onChange={async event => {
              const file = event.target.files?.[0]; if (!file) return;
              try { setProductPhoto(await readPhoto(file)); } catch (failure) { setError(failure.message); }
            }} />
            {productPhoto && <img src={productPhoto} alt="Reference preview" className="w-full h-32 object-contain" />}
            <Input aria-label="Product name" placeholder="Product name" value={productName} onChange={event => setProductName(event.target.value)} disabled={busy} />
            <Input aria-label="Category" placeholder="Category" value={category} onChange={event => setCategory(event.target.value)} disabled={busy} />
            <Button variant="outline" onClick={ingest} disabled={busy || !available || !productPhoto || !productName.trim() || !category.trim()}>Add reference</Button>
          </div></details>
        </>}
        <details className="border-y border-foreground/15 py-3"><summary className="text-sm cursor-pointer">Parameters</summary>
          <div className="space-y-4 pt-4">
            <label className="block text-sm">Steps: {steps}<input aria-label="Steps" type="range" min="12" max="50" value={steps} disabled={busy} onChange={event => setSteps(event.target.value)} className="block w-full mt-2 accent-accent" /></label>
            <label className="block text-sm">Guidance: {guidance}<input aria-label="Guidance" type="range" min="1" max="15" step="0.5" value={guidance} disabled={busy} onChange={event => setGuidance(event.target.value)} className="block w-full mt-2 accent-accent" /></label>
            <label className="block text-sm">Mask expansion: {growth}<input aria-label="Mask expansion" type="range" min="0" max="24" value={growth} disabled={busy} onChange={event => { setGrowth(event.target.value); }} className="block w-full mt-2 accent-accent" /></label>
            {mode === "reference" && <label className="block text-sm">Reference strength: {ipScale}<input aria-label="Reference strength" type="range" min="0" max="1.5" step="0.05" value={ipScale} disabled={busy} onChange={event => setIpScale(event.target.value)} className="block w-full mt-2 accent-accent" /></label>}
            <label className="flex items-center justify-between text-sm" htmlFor="random-seed">Random seed<input id="random-seed" type="checkbox" checked={randomSeed} disabled={busy} onChange={event => setRandomSeed(event.target.checked)} className="w-4 h-4 accent-accent" /></label>
            <label className="block text-sm space-y-2"><span>Seed</span><Input type="number" aria-label="Seed" min="0" max="4294967295" value={seed} disabled={busy || randomSeed} onChange={event => setSeed(event.target.value)} /></label>
            <label className="block text-sm space-y-2"><span>Negative prompt</span><Input aria-label="Negative prompt" value={negative} disabled={busy} onChange={event => setNegative(event.target.value)} /></label>
          </div>
        </details>
        <Button className="w-full" variant="accent" icon={<LuSparkles />} onClick={generate} disabled={busy || !canGenerate}>Replace furniture</Button>
      </aside>
    </div>
  </div>;
}