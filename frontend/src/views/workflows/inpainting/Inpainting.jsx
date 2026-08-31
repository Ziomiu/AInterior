import React from "react";
import axios from "axios";
import { LuX } from "react-icons/lu";
import { FiUpload } from 'react-icons/fi';
import { useState, useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import CanvasPreview from "./Canvas";
import Prompts from "../../../components/Prompts";
import { toaster } from "../../../components/ui/toaster";
import TextTooltip from "../../../components/TextTooltip";
import SliderControl from "../../../components/SliderControl";
import InpaintingCanvas from "../../../components/InpaintingCanvas";
import RedirectButtons from "../../../components/QuickRedirectButtons";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Input from "../../../components/ui/Input";
import Toggle from "../../../components/ui/Toggle";
import { saveToCanvas } from "../canvas/utilities/saveToCanvas";

const Inpainting = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [image, updateImage] = useState();
  const [loadedImage, setLoadedImage] = useState(null);
  const [maskData, setMaskData] = useState(null);
  const [prompt, updatePrompt] = useState("");
  const [negativePrompt, updateNegativePrompt] = useState("");
  const [loading, updateLoading] = useState(false);
  const [guidance, setGuidance] = useState(8);
  const [randomizeSeed, setRandomizeSeed] = useState(true);
  const [seed, setSeed] = useState(Math.floor(Math.random() * 999999999999999));
  const [model, setModel] = useState("juggernaut-inpainting");
  const [imageDimensions, setImageDimensions] = useState({ width: 512, height: 512 });
  const [maskEditorOpen, setMaskEditorOpen] = useState(false);

  const shouldRedirectToCanvas = searchParams.get('shouldRedirectToCanvas') || "false";

  const [showAdvancedParameters, setShowAdvancedParameters] = useState(false);

  const fileInputRef = useRef(null);

  useEffect(() => {
    const stored = localStorage.getItem("selectedImage");
    if (stored) {
      try {
        const data = JSON.parse(stored);
        if (data) {
          const img = new Image();
          img.src = `data:image/png;base64,${data.image_base64}`;
          img.onload = () => {
            const validatedWidth = Math.round(img.width / 8) * 8;
            const validatedHeight = Math.round(img.height / 8) * 8;
            setImageDimensions({ width: validatedWidth, height: validatedHeight });
            setLoadedImage(`data:image/png;base64,${data.image_base64}`);
            updatePrompt(data.prompt || "");
            updateNegativePrompt(data.negative_prompt || "");
            setGuidance(data.guidance_scale || 7.0);
            setSeed(data.seed || 0);
            setMaskEditorOpen(true);
          };
        }
      } catch (err) {
        console.error("Failed to parse stored image data", err);
      } finally {
        localStorage.removeItem("selectedImage");
      }
    }
  }, []);

  const handleFileChange = (event) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onloadend = () => {
      const img = new Image();
      img.src = reader.result;
      img.onload = () => {
        const validatedWidth = Math.round(img.width / 8) * 8;
        const validatedHeight = Math.round(img.height / 8) * 8;
        setImageDimensions({ width: validatedWidth, height: validatedHeight });
        setLoadedImage(reader.result);
        setMaskData(null);
      };
    };
    reader.readAsDataURL(file);
  };

  const unloadImage = () => {
    setLoadedImage(null);
    setMaskData(null);
    setImageDimensions({ width: 512, height: 512 });
    setMaskEditorOpen(false);
    updateImage(null);
    if (fileInputRef.current) fileInputRef.current.value = null;
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

    if (!loadedImage) {
      toaster.create({
        title: "Missing image",
        description: "You must load an image.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
      return;
    }

    if (!maskData) {
      toaster.create({
        title: "Missing mask",
        description: "You must draw a mask on the image.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
      return;
    }

    var seed_to_use = seed;
    if (randomizeSeed) {
      seed_to_use = Math.floor(Math.random() * 999999999);
      setSeed(seed_to_use);
    }

    updateLoading(true);

    try {
      const response = await axios.post(
        `/api/model/generate/inpainting`,
        {
          model_version: model,
          image: loadedImage.split(",")[1],
          mask_image: maskData.split(",")[1],
          prompt: prompt,
          negative_prompt: negativePrompt,
          guidance_scale: guidance,
          seed: seed,
          strength: 1.0
        },
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      updateImage(response.data.image);

      if (shouldRedirectToCanvas === "true") {
        try {
          const parentImageId = localStorage.getItem("parentImageId");

          saveToCanvas(
            response.data.image,
            {
              prompt,
              negative_prompt: negativePrompt,
              workflow: "inpainting",
              guidance_scale: guidance,
              seed: seed_to_use
            },
            parentImageId
          );


          const currentCanvasId = localStorage.getItem('currentCanvasId');

          setTimeout(() => {
            //navigate("/views/workflows/canvas");
            navigate(
              `/views/workflows/canvas?${new URLSearchParams({
                redirectToWorkflow: currentCanvasId,
              }).toString()}`)
          }, 600);
        } catch (e) {
          console.error("Inpainting canvas redirect error:", e);
        }
      }
    } catch (error) {
      console.error("Error:", error.response?.data?.detail || error.message);
      toaster.create({
        title: "Generation failed",
        description: error.response?.data?.detail || "Could not generate image.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    } finally {
      updateLoading(false);
    }
  };

  const openMaskEditor = () => {
    if (!loadedImage) {
      toaster.create({
        title: "No image loaded",
        description: "Please load an image first.",
        status: "warning",
        duration: 3000,
        isClosable: true,
      });
      return;
    }
    setMaskEditorOpen(true);
  };

  return (
    <div className="min-h-screen flex flex-col justify-center items-center p-4">
      <Card className="w-full max-w-[1800px] p-5">

        {shouldRedirectToCanvas === "true" ?
          <h1 className="font-bold text-3xl mb-5">Inpainting (Canvas)</h1> :
          <h1 className="font-bold text-3xl mb-5">Inpainting</h1>
        }

        <div className="flex flex-col xl:flex-row gap-8">
          <div className="flex-1 flex flex-col">
            <div className="w-full h-full border-2 border-dashed border-foreground/20 rounded-lg bg-foreground/5 hover:bg-foreground/10 transition-colors">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleFileChange}
                className="hidden"
                id="file-input"
              />
              {loadedImage == null ? (
                <label
                  htmlFor="file-input"
                  className="w-full h-full flex flex-col items-center justify-center cursor-pointer"
                >
                  <FiUpload size={23} className="mb-2 text-muted" />
                  <p className="text-foreground/85">Drag and drop files here</p>
                  <p className="text-muted text-sm">.png, .jpg up to 5MB</p>
                </label>
              ) : (
                <div className="relative w-full h-full">
                  <CanvasPreview
                    original={loadedImage}
                    mask={maskData}
                    width={imageDimensions.width}
                    height={imageDimensions.height}
                  />
                  <button
                    className="absolute top-2 right-2 bg-foreground text-background rounded-full p-2 hover:opacity-90 transition cursor-pointer"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      unloadImage();
                    }}
                  >
                    <LuX />
                  </button>
                  <button
                    className="absolute bottom-2 right-2 bg-primary text-primary-foreground px-4 py-2 rounded hover:opacity-90 transition cursor-pointer"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      openMaskEditor();
                    }}
                  >
                    {maskData ? "Edit Mask" : "Draw Mask"}
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="flex-1 aspect-square flex items-center justify-center bg-foreground/5 rounded-md overflow-hidden relative">
            {loading ? (
              <div className="flex flex-col items-center justify-center gap-2 animate-pulse w-full h-full">
                <div className="rounded-full bg-foreground/10 h-12 w-12"></div>
                <div className="h-4 bg-foreground/10 rounded w-3/4"></div>
                <div className="h-4 bg-foreground/10 rounded w-1/2"></div>
              </div>
            ) : (
              <>
                {image ? (
                  <>
                    <img src={`data:image/png;base64,${image}`} className="object-contain w-full h-full rounded-md shadow-lg" />

                    <RedirectButtons
                      image={image}
                      setLoadedImage={setLoadedImage}
                      updateImage={updateImage}
                    />
                  </>
                ) : (
                  <div className="flex flex-col items-center justify-center text-muted">
                    <p>Generated image will appear here</p>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
        <div className="w-full max-w-[1800px] flex flex-col gap-4 mt-8">
          <Prompts positivePrompt={prompt} setPositivePrompt={updatePrompt} negativePrompt={negativePrompt} setNegativePrompt={updateNegativePrompt} />

          {showAdvancedParameters ? (
            <>
              <Button
                variant="outline"
                size="md"
                onClick={() => setShowAdvancedParameters(false)}
                className="self-start normal-case tracking-normal"
              >
                Hide advanced parameters ▲
              </Button>


              <SliderControl label="Guidance scale" description="Controls how strictly the model follows the prompt. The recommended value is 7 or 8." value={guidance} min={0} max={25} step={0.1} onChange={(v) => setGuidance(v[0])} />

              <div className="flex items-center space-x-3">
                <TextTooltip
                  text="Auto randomize seed"
                  tooltip="Enable or disable automatic seed randomization."
                />
                <Toggle checked={randomizeSeed} onChange={setRandomizeSeed} />
              </div>

              <div className="flex flex-col gap-2">
                <TextTooltip
                  text="Seed"
                  tooltip="Controls the randomness in image generation. Keeping it fixed while adjusting other parameters will produce very similar images."
                />
                <div className="flex gap-4 items-center">
                  <Input
                    type="number"
                    value={seed}
                    min={0}
                    max={999999999}
                    onChange={(e) => setSeed(Number(e.target.value))}
                    disabled={randomizeSeed}
                  />
                  <Button
                    variant="outline"
                    size="md"
                    onClick={() => setSeed(Math.floor(Math.random() * 999999999))}
                    disabled={randomizeSeed}
                    className="normal-case tracking-normal shrink-0"
                  >
                    Randomize
                  </Button>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <TextTooltip
                  text="Choose model"
                  tooltip="Choose the Stable Diffusion model version. Generally, a higher version means better quality but longer generation times."
                />
                <div className="flex gap-4 flex-wrap">
                  {["1.5-inpainting", "2.0-inpainting", "xl-inpainting", "juggernaut-inpainting"].map((version) => (
                    <button
                      key={version}
                      onClick={() => setModel(version)}
                      className={`rounded-2xl border-2 px-4 py-2 transition cursor-pointer ${model === version ? "bg-primary text-primary-foreground border-primary" : "text-foreground bg-transparent border-foreground/20 hover:bg-foreground/5"}`}
                    >
                      {version}
                    </button>
                  ))}
                </div>
              </div>

            </>
          ) : (
            <Button
              variant="outline"
              size="md"
              onClick={() => setShowAdvancedParameters(true)}
              className="self-start normal-case tracking-normal"
            >
              Show advanced parameters ▼
            </Button>
          )}

          <Button
            variant="accent"
            onClick={generate}
            disabled={!loadedImage || !maskData || loading}
            className="mt-auto w-full normal-case tracking-normal"
          >
            {loading ? "Generating..." : "Generate"}
          </Button>

        </div>
      </Card>
      {
        maskEditorOpen && (
          <div className="fixed top-0 left-0 w-screen h-screen z-[9999] flex justify-center items-center">
            <div className="fixed top-0 left-0 w-screen h-screen z-[9999] flex justify-center items-center bg-foreground/90" />
            <div className="relative z-[9999] flex justify-center items-center">
              <InpaintingCanvas
                imageSrc={loadedImage}
                onMaskUpdate={setMaskData}
                width={imageDimensions.width}
                height={imageDimensions.height}
                setMaskEditorOpenRef={setMaskEditorOpen}
              />
            </div>
          </div>
        )
      }
    </div>
  );
};

export default Inpainting;