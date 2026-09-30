import React from "react";
import axios from "axios";
import { useState, useEffect } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";

import Prompts from "../../../components/Prompts";
import { toaster } from "../../../components/ui/toaster";
import TextTooltip from "../../../components/TextTooltip";
import SliderControl from "../../../components/SliderControl";
import RedirectButtons from "../../../components/QuickRedirectButtons";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Input from "../../../components/ui/Input";
import Toggle from "../../../components/ui/Toggle";
import { saveToCanvas } from "../canvas/utilities/saveToCanvas";

const TextToImage = () => {
  const [image, updateImage] = useState();
  const [prompt, updatePrompt] = useState("");
  const [negativePrompt, updateNegativePrompt] = useState("");
  const [loading, updateLoading] = useState(false);
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [guidance, setGuidance] = useState(7.0);
  const [randomizeSeed, setRandomizeSeed] = useState(true);
  const [seed, setSeed] = useState(Math.floor(Math.random() * 999999999999999));
  const [model, setModel] = useState("xl");

  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const urlPrompt = searchParams.get("prompt");
  const urlNegativePrompt = searchParams.get("negativePrompt");
  const urlWidth = searchParams.get("width");
  const urlHeight = searchParams.get("height");
  const urlGuidance = searchParams.get("guidance");
  const urlSeed = searchParams.get("seed");
  const urlModel = searchParams.get("model");

  const shouldRedirectToCanvas = searchParams.get('shouldRedirectToCanvas') || "false";

  const [showAdvancedParameters, setShowAdvancedParameters] = useState(false);

  useEffect(() => {
    if (urlPrompt) updatePrompt(urlPrompt);
  }, [urlPrompt]);

  useEffect(() => {
    if (urlNegativePrompt) updateNegativePrompt(urlNegativePrompt);
  }, [urlNegativePrompt]);

  useEffect(() => {
    if (urlWidth) setWidth(urlWidth);
  }, [urlWidth]);

  useEffect(() => {
    if (urlHeight) setHeight(urlHeight);
  }, [urlHeight]);

  useEffect(() => {
    if (urlGuidance) setGuidance(urlGuidance);
  }, [urlGuidance]);

  useEffect(() => {
    if (urlSeed) setSeed(urlSeed);
  }, [urlSeed]);

  useEffect(() => {
    if (urlModel) setModel(urlModel);
  }, [urlModel]);

  useEffect(() => {
    const stored = localStorage.getItem("selectedImage");
    if (stored) {
      try {
        const data = JSON.parse(stored);
        if (data) {
          updatePrompt(data.prompt || "");
          updateNegativePrompt(data.negative_prompt || "");
          setGuidance(data.guidance_scale || 7);
          setSeed(data.seed || 0);
          setWidth(data.width || 512);
          setHeight(data.height || 512);
          localStorage.removeItem("selectedImage");
        }
      } catch (e) {
        console.error("Invalid image data", e);
      }
    }
  }, []);

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

    var seed_to_use = seed;
    if (randomizeSeed) {
      seed_to_use = Math.floor(Math.random() * 999999999);
      setSeed(seed_to_use);
    }

    updateLoading(true);
    try {
      const response = await axios.post(
        `/api/model/generate/text-to-image`,
        { model_version: model, prompt, negative_prompt: negativePrompt, guidance_scale: guidance, width: width, height: height, seed: seed_to_use },
        { headers: { Authorization: `Bearer ${token}` } }
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
              workflow: "text-to-image",
              guidance_scale: guidance,
              seed: seed_to_use
            },
            parentImageId
          );

          const currentCanvasId =  localStorage.getItem('currentCanvasId');
          
          setTimeout(() => {
            //navigate("/views/workflows/canvas");
            navigate(
              `/views/workflows/canvas?${new URLSearchParams({
                redirectToWorkflow: currentCanvasId,
              }).toString()}`)
          }, 600);

        } catch (e) {

          console.error("Txt 2 Img context error:", e);
        }
      }


    } catch (error) {

      /*
        This message is most likely to be triggered when user sends request with exact same
        parameters as previous one. Since ComfyUI is smart it does not regenerate the image,
        hence providing no output. BUT since the data stays the same we can ignore it, making
        us also benefit from this by not saving redundant data to the database!
      */
      if (error.response?.data?.detail == "No outputs found in workflow response") {
        return
      }

      console.error("Error:", error);

      toaster.create({
        title: "Generation failed",
        description: error.response?.data?.detail || "Something went wrong.",
        status: "error",
        duration: 3000,
        isClosable: true,
      });
    } finally {
      updateLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-4">
      <Card className="w-full max-w-[1800px] flex flex-col xl:flex-row gap-8 p-5">
        {/* Panel */}
        <div className="flex-1 flex flex-col gap-4">
          {shouldRedirectToCanvas === "true" ?
            <h1 className="font-bold text-3xl mb-5">Text to image (Canvas)</h1> :
            <h1 className="font-bold text-3xl mb-5">Text to image</h1>
          }

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


              <SliderControl label="Width" description="Width of the generated image." value={width} min={64} max={1024} step={64} onChange={(v) => setWidth(v[0])} />
              <SliderControl label="Height" description="Height of the generated image." value={height} min={64} max={1024} step={64} onChange={(v) => setHeight(v[0])} />

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
                  {["1.5", "2.1", "3.0", "xl"].map((version) => (
                    <button
                      key={version}
                      onClick={() => setModel(version)}
                      className={`rounded-2xl border-2 px-4 py-2 w-24 transition cursor-pointer ${model === version ? "bg-primary text-primary-foreground border-primary" : "text-foreground bg-transparent border-foreground/20 hover:bg-foreground/5"}`}
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
            disabled={loading}
            className="mt-auto w-full normal-case tracking-normal"
          >
            {loading ? "Generating..." : "Generate"}
          </Button>

        </div>
        {/* Preview */}
        <div className="flex-1 aspect-square flex items-center justify-center bg-foreground/5 rounded-md overflow-hidden relative">
          {loading ? (
            <div className="flex flex-col items-center justify-center gap-2 animate-pulse w-full h-full">
              <div className="rounded-full bg-foreground/10 h-12 w-12"></div>
              <div className="h-4 bg-foreground/10 rounded w-3/4"></div>
              <div className="h-4 bg-foreground/10 rounded w-1/2"></div>
            </div>
          ) : (
            image ? (
              <>
                <img src={`data:image/png;base64,${image}`} className="object-contain w-full h-full rounded-md shadow-lg" />

                <RedirectButtons
                  image={image}
                  setLoadedImage={null}
                  updateImage={null}
                />
              </>
            ) : (
              <div className="flex flex-col items-center justify-center text-muted">
                <p>Generated image will appear here</p>
              </div>
            )
          )}
        </div>
      </Card>
    </div>
  );
};

export default TextToImage;