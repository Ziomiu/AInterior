import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { LuCheck, LuDownload, LuEraser, LuImagePlus, LuMinus, LuMousePointer2, LuPaintbrush, LuPlus, LuRefreshCw, LuSave, LuSearch, LuSlidersHorizontal, LuSparkles, LuUndo2, LuX } from "react-icons/lu";
import Button from "../../../components/ui/Button";
import Input from "../../../components/ui/Input";
import FurnitureMaskCanvas from "../../../components/FurnitureMaskCanvas";
import { toaster } from "../../../components/ui/toaster";

const base64 = source => source.split(",")[1];
const options = signal => ({ headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }, signal });
const stageLabels = {
  queued: "Queued", waiting_for_gpu: "Waiting for GPU", preparing: "Preparing image",
  loading: "Loading model",
  loading_segmenter: "Loading selection model", segmenting: "Selecting furniture",
  loading_classifier: "Loading recognition model", classifying: "Recognizing furniture",
  loading_cleaner: "Loading cleanup model", cleaning: "Removing furniture",
  loading_generator: "Loading replacement model", generating: "Generating replacement",
  compositing: "Blending replacement", saving: "Saving image", running: "Processing",
};
const categoryAliases = { armchair: "chair", chairs: "chair", couch: "sofa", sofas: "sofa", tables: "table", bookshelf: "shelf", shelving: "shelf", wardrobe: "cabinet", dresser: "cabinet", beds: "bed" };
const normalizedCategory = value => {
  const category = (value || "").trim().toLowerCase();
  return categoryAliases[category] || category;
};

export async function waitForFurnitureJob(jobId, signal, onStatus) {
  const deadline = Date.now() + 600000;
  while (!signal.aborted && Date.now() < deadline) {
    const response = await axios.get(`/api/furniture/jobs/${jobId}`, options(signal));
    onStatus(response.data.stage || response.data.status);
    if (signal.aborted) throw new DOMException("Stopped waiting", "AbortError");
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
  const [tool, setTool] = useState("select");
  const [correcting, setCorrecting] = useState(false);
  const [classification, setClassification] = useState(null);
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [brushSize, setBrushSize] = useState(24);
  const [mode, setMode] = useState("reference");
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
  const [elapsed, setElapsed] = useState(0);
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
      } catch { setError("Could not load the selected gallery image"); }
      localStorage.removeItem("selectedImage");
    }
    return () => { controller.abort(); controllerRef.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);

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

  const resetMask = () => { setMask(null); setMaskJob(null); setAccepted(false); setClassification(null); setCategoryFilter("all"); setResult(null); setSaved(false); };
  const choosePhoto = async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const source = await readPhoto(file);
      setPhoto(source); setPoints([]); resetMask(); setSelected(null); setError(""); setCorrecting(false); setTool("select");
    } catch (failure) { setError(failure.message); }
    event.target.value = "";
  };

  const segment = nextPoints => run(async signal => {
    setAccepted(false);
    setStatus("queued");
    const response = await axios.post("/api/furniture/segment", { image: base64(photo), points: nextPoints }, options(signal));
    const outcome = await waitForFurnitureJob(response.data.job_id, signal, setStatus);
    setMask(`data:image/png;base64,${outcome.mask}`);
    setMaskJob(response.data.job_id);
    setClassification(outcome.classification || null);
    setCategoryFilter(outcome.classification && !outcome.classification.uncertain && outcome.classification.category !== "unknown" ? normalizedCategory(outcome.classification.category) : "all");
    setAccepted(outcome.mask_review_required === false);
    setResult(null); setSaved(false);
  });

  const selectPoint = point => {
    const nextPoints = correcting ? [...points, point].slice(-64) : [{ ...point, label: 1 }];
    setPoints(nextPoints); resetMask();
    if (nextPoints.some(next => next.label)) segment(nextPoints);
  };

  const match = () => run(async signal => {
    setStatus("Searching catalog");
    const response = await axios.post("/api/furniture/match", {
      image: base64(photo), mask: base64(mask), mask_job_id: maskJob,
    }, options(signal));
    const matches = response.data.matches;
    setProducts(previous => [...matches, ...previous.filter(product => !matches.some(match => match.product_id === product.product_id))]);
  });

  const ingest = () => run(async signal => {
    setStatus("Indexing reference");
    const response = await axios.post("/api/furniture/products", {
      image: base64(productPhoto), name: productName.trim(), category: category.trim(),
    }, options(signal));
    setProducts(previous => [response.data, ...previous]); setSelected(response.data);
    setMode("reference"); setQuality("balanced"); setCategoryFilter("all"); setSearch(""); setProductPhoto(null); setProductName("");
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
  const categories = [...new Set(products.map(product => normalizedCategory(product.category)).filter(Boolean))].sort();
  if (categoryFilter !== "all" && !categories.includes(categoryFilter)) categories.push(categoryFilter);
  const visibleProducts = products.filter(product => (categoryFilter === "all" || normalizedCategory(product.category) === categoryFilter)
    && `${product.name} ${product.category || ""} ${product.description || ""}`.toLowerCase().includes(search.trim().toLowerCase()));

  return <div className="w-full max-w-[1600px] mx-auto min-h-screen p-4 md:p-6 space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-foreground/15 pb-4">
      <h1 className="font-serif text-3xl font-bold">Furniture Replace</h1>
      <div className="flex items-center gap-2 text-sm text-muted">
        <span className={`w-2 h-2 rounded-full ${available ? "bg-accent" : "bg-red-500"}`} />
        <span>{available === null ? "Connecting" : available ? "Service ready" : "Service unavailable"}</span>
        {iconButton("Refresh service", <LuRefreshCw />, () => refresh())}
      </div>
    </header>
    {error && <div role="alert" className="border-l-2 border-red-500 bg-red-500/5 p-3 text-sm">{error}</div>}
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px] gap-6 lg:gap-8">
      <section className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <label className={`inline-flex items-center gap-2 px-4 py-2 border border-foreground/20 rounded-sm text-sm ${busy ? "opacity-40" : "cursor-pointer hover:bg-foreground/5"}`}>
            <LuImagePlus /> Photo
            <input aria-label="Room photo" className="hidden" type="file" accept="image/*" disabled={busy} onChange={choosePhoto} />
          </label>
          {iconButton("Select furniture", <LuMousePointer2 />, () => { setCorrecting(false); setTool("select"); setComparison("original"); }, !photo, !correcting)}
          <button type="button" onClick={() => { setCorrecting(!correcting); setTool(correcting ? "select" : "include"); setComparison("original"); }} disabled={busy || !mask}
            aria-expanded={correcting} className="inline-flex items-center gap-2 px-3 h-10 text-sm border border-foreground/20 rounded-sm disabled:opacity-40 hover:bg-foreground/5"><LuSlidersHorizontal /> Correct mask</button>
          {iconButton("Clear selection", <LuX />, () => { setPoints([]); resetMask(); setCorrecting(false); setTool("select"); }, !photo)}
        </div>
        {correcting && <div role="toolbar" aria-label="Mask correction" className="flex flex-wrap items-center gap-2 border-t border-foreground/10 pt-3">
          {iconButton("Include point", <LuPlus />, () => setTool("include"), !photo, tool === "include")}
          {iconButton("Exclude point", <LuMinus />, () => setTool("exclude"), !photo, tool === "exclude")}
          {iconButton("Paint mask", <LuPaintbrush />, () => setTool("paint"), !mask, tool === "paint")}
          {iconButton("Erase mask", <LuEraser />, () => setTool("erase"), !mask, tool === "erase")}
          {iconButton("Undo", <LuUndo2 />, () => {
            if (tool === "paint" || tool === "erase") editorRef.current?.undo();
            else {
              const nextPoints = points.slice(0, -1); setPoints(nextPoints); resetMask();
              if (nextPoints.some(point => point.label)) segment(nextPoints);
            }
          }, !photo)}
          {(tool === "paint" || tool === "erase") && <input aria-label="Brush size" type="range" min="4" max="100" value={brushSize} onChange={event => setBrushSize(Number(event.target.value))} className="w-24 accent-accent" />}
        </div>}
        {result && <div role="tablist" aria-label="Image comparison" className="inline-flex border border-foreground/20 rounded-sm">
          {["original", "result"].map(tab => <button role="tab" aria-selected={comparison === tab} key={tab} onClick={() => setComparison(tab)} className={`px-4 py-2 text-sm capitalize ${comparison === tab ? "bg-foreground text-background" : "hover:bg-foreground/5"}`}>{tab}</button>)}
        </div>}
        <div className="border border-foreground/10 bg-foreground/[0.025] min-h-[280px] overflow-hidden rounded-md">
          {result && comparison === "result" ? <img src={`data:image/png;base64,${result.image}`} alt="Replacement result" className="w-full h-auto" />
            : photo ? <FurnitureMaskCanvas key={maskJob || "unsegmented"} ref={editorRef} image={photo} mask={mask} points={points} tool={tool} brushSize={brushSize} disabled={busy || !available}
              onPoint={selectPoint}
              onMaskChange={next => { setMask(next); setAccepted(false); setClassification(null); setCategoryFilter("all"); setResult(null); setSaved(false); }} />
            : <label className="min-h-[360px] md:min-h-[520px] flex flex-col items-center justify-center text-muted gap-4 cursor-pointer bg-[radial-gradient(circle_at_1px_1px,rgba(120,142,109,0.12)_1px,transparent_0)] bg-[size:20px_20px]">
              <LuImagePlus size={36} /><span className="text-sm">Add room photo</span>
              <input aria-label="Upload room photo" className="hidden" type="file" accept="image/*" disabled={busy} onChange={choosePhoto} />
            </label>}
        </div>
        {mask && <div className="flex flex-wrap items-center justify-between gap-3 border-b border-foreground/10 pb-4">
          <div className="min-w-0 flex flex-wrap items-center gap-2 text-sm">
            <span className="w-2 h-2 bg-accent rounded-full" />
            <strong className="capitalize">{classification?.uncertain ? "Unknown furniture" : classification?.label || "Selected furniture"}</strong>
            {Number.isFinite(classification?.confidence) && <span className="text-muted" title="Relative CLIP score, not a calibrated probability">Match confidence {Math.round(classification.confidence * 100)}%</span>}
            {accepted && <span className="inline-flex items-center gap-1 text-accent"><LuCheck /> Ready</span>}
          </div>
          {!accepted && <div className="flex flex-wrap items-center gap-3"><span className="text-sm text-muted">Mask review required</span><Button variant="outline" icon={<LuCheck />} onClick={() => setAccepted(true)} disabled={busy}>Accept mask</Button></div>}
        </div>}
        {busy && <div role="status" aria-live="polite" className="flex items-center gap-3 text-sm text-muted py-2">
          <LuRefreshCw className="animate-spin shrink-0" /><span>{stageLabels[status] || status || "Processing"}</span><span className="ml-auto tabular-nums shrink-0">{elapsed}s elapsed</span>
        </div>}
        {result && <section className="border-t border-foreground/15 pt-4 space-y-3">
          <span className="text-sm text-muted">{result.elapsed_seconds}s · seed {result.seed}</span>
          <div className="flex gap-3 flex-wrap">
            <Button icon={<LuSave />} onClick={save} disabled={busy || saved}>{saved ? "Saved" : "Save to gallery"}</Button>
            <a href={`data:image/png;base64,${result.image}`} download="furniture-replacement.png" className="inline-flex items-center gap-2 border border-foreground/20 px-4 py-2 rounded-sm text-sm"><LuDownload /> Download</a>
          </div>
        </section>}
      </section>
      <aside aria-label="Replacement panel" className="min-w-0 space-y-5 lg:border-l lg:border-foreground/10 lg:pl-6">
        <h2 className="font-serif text-xl font-semibold">Replacement</h2>
        <div role="tablist" aria-label="Replacement mode" className="grid grid-cols-2 border border-foreground/20 rounded-sm">
          {["reference", "prompt"].map(tab => <button role="tab" aria-selected={mode === tab} disabled={busy} key={tab} onClick={() => { setMode(tab); if (tab === "reference") setQuality("balanced"); }} className={`px-3 py-2 text-sm ${mode === tab ? "bg-foreground text-background" : "hover:bg-foreground/5"}`}>{tab === "reference" ? "Catalog" : "Description"}</button>)}
        </div>
        {mode === "prompt" ? <>
          <label className="block text-sm space-y-2"><span>Replacement description</span><textarea aria-label="Replacement description" placeholder="An olive velvet armchair with oak legs" value={prompt} onChange={event => setPrompt(event.target.value)} disabled={busy} rows={4} maxLength={2000} className="w-full p-3 rounded-md border border-foreground/15 bg-transparent focus:ring-2 focus:ring-accent outline-none" /></label>
        </> : <>
          <div className="relative"><LuSearch className="absolute left-3 top-3 text-muted pointer-events-none" /><input aria-label="Search catalog" type="search" placeholder="Search furniture" value={search} onChange={event => setSearch(event.target.value)} disabled={busy} className="w-full pl-9 pr-3 py-2 border border-foreground/15 rounded-sm bg-transparent text-sm focus:outline-accent" /></div>
          <div className="flex items-center gap-2">
            <select aria-label="Catalog category" value={categoryFilter} onChange={event => setCategoryFilter(event.target.value)} disabled={busy} className="min-w-0 flex-1 text-sm capitalize bg-transparent border border-foreground/15 rounded-sm px-2 py-2">
              <option value="all">All categories</option>{categories.map(category => <option key={category} value={category}>{category}</option>)}
            </select>
            {iconButton("Find similar products", <LuSparkles />, match, !accepted || !available)}
          </div>
          <div className="grid grid-cols-2 gap-3 max-h-[480px] overflow-y-auto p-1 -m-1">
            {visibleProducts.map(product => <button type="button" key={product.product_id} disabled={busy} onClick={() => setSelected(product)} aria-pressed={selected?.product_id === product.product_id}
              className={`text-left border rounded-md overflow-hidden transition-colors hover:border-accent focus-visible:outline-accent ${selected?.product_id === product.product_id ? "border-accent ring-1 ring-accent bg-accent/5" : "border-foreground/10"}`}>
              <div className="relative aspect-square bg-white/50"><img src={`data:image/png;base64,${product.image}`} alt={product.name} className="w-full h-full object-contain p-2" />{selected?.product_id === product.product_id && <span className="absolute top-2 right-2 w-6 h-6 flex items-center justify-center rounded-full bg-accent text-white"><LuCheck /></span>}</div>
              <span className="block px-3 pt-2 pb-1 text-sm font-medium break-words">{product.name}</span>
              <span className="block px-3 pb-3 text-xs text-muted capitalize break-words">{product.category || "Furniture"}</span>
            </button>)}
          </div>
          {!visibleProducts.length && <div className="py-6 text-center space-y-3"><p className="text-sm text-muted">{products.length ? "No matching products" : "No catalog products"}</p>{categoryFilter !== "all" && <button type="button" className="text-sm underline underline-offset-4" onClick={() => setCategoryFilter("all")}>All categories</button>}</div>}
          {selected && <div className="flex items-center gap-3 border-t border-foreground/10 pt-3 text-sm"><LuCheck className="text-accent shrink-0" /><span className="min-w-0 break-words flex-1">{selected.name}</span>{iconButton("Clear product", <LuX />, () => setSelected(null))}</div>}
        </>}
        <Button className="w-full !tracking-normal !text-sm !normal-case" variant="accent" icon={<LuSparkles />} onClick={generate} disabled={busy || !canGenerate}>Replace</Button>
        {mode === "reference" && <details className="border-y border-foreground/15 py-3"><summary className="cursor-pointer text-sm">Add reference</summary><div className="space-y-3 pt-3">
            <input aria-label="Reference photo" type="file" accept="image/*" disabled={busy} className="w-full text-sm" onChange={async event => {
              const file = event.target.files?.[0]; if (!file) return;
              try { setProductPhoto(await readPhoto(file)); } catch (failure) { setError(failure.message); }
            }} />
            {productPhoto && <img src={productPhoto} alt="Reference preview" className="w-full h-32 object-contain" />}
            <Input aria-label="Product name" placeholder="Product name" value={productName} onChange={event => setProductName(event.target.value)} disabled={busy} />
            <Input aria-label="Category" placeholder="Category" value={category} onChange={event => setCategory(event.target.value)} disabled={busy} />
            <Button variant="outline" onClick={ingest} disabled={busy || !available || !productPhoto || !productName.trim() || !category.trim()}>Add reference</Button>
          </div></details>}
        <details className="border-b border-foreground/15 pb-3"><summary className="text-sm cursor-pointer">Advanced settings</summary>
          <div className="space-y-4 pt-4">
            {mode === "prompt" && <fieldset disabled={busy} className="space-y-2"><legend className="text-sm mb-2">Generation profile</legend><div className="flex border border-foreground/20 rounded-sm">
              {["balanced", "quality"].map(profile => <button type="button" key={profile} aria-pressed={quality === profile} onClick={() => setQuality(profile)} className={`flex-1 p-2 text-sm capitalize ${quality === profile ? "bg-accent text-accent-foreground" : "hover:bg-foreground/5"}`}>{profile}</button>)}
            </div></fieldset>}
            <label className="block text-sm">Steps: {steps}<input aria-label="Steps" type="range" min="12" max="50" value={steps} disabled={busy} onChange={event => setSteps(event.target.value)} className="block w-full mt-2 accent-accent" /></label>
            <label className="block text-sm">Guidance: {guidance}<input aria-label="Guidance" type="range" min="1" max="15" step="0.5" value={guidance} disabled={busy} onChange={event => setGuidance(event.target.value)} className="block w-full mt-2 accent-accent" /></label>
            <label className="block text-sm">Mask expansion: {growth}<input aria-label="Mask expansion" type="range" min="0" max="24" value={growth} disabled={busy} onChange={event => { setGrowth(event.target.value); }} className="block w-full mt-2 accent-accent" /></label>
            {mode === "reference" && <label className="block text-sm">Reference strength: {ipScale}<input aria-label="Reference strength" type="range" min="0" max="1.5" step="0.05" value={ipScale} disabled={busy} onChange={event => setIpScale(event.target.value)} className="block w-full mt-2 accent-accent" /></label>}
            <label className="flex items-center justify-between text-sm" htmlFor="random-seed">Random seed<input id="random-seed" type="checkbox" checked={randomSeed} disabled={busy} onChange={event => setRandomSeed(event.target.checked)} className="w-4 h-4 accent-accent" /></label>
            <label className="block text-sm space-y-2"><span>Seed</span><Input type="number" aria-label="Seed" min="0" max="4294967295" value={seed} disabled={busy || randomSeed} onChange={event => setSeed(event.target.value)} /></label>
            <label className="block text-sm space-y-2"><span>Negative prompt</span><Input aria-label="Negative prompt" value={negative} disabled={busy} onChange={event => setNegative(event.target.value)} /></label>
          </div>
        </details>
      </aside>
    </div>
  </div>;
}