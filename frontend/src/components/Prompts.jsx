import React from "react";
import { useState} from "react";

import TextTooltip from "./TextTooltip";
import VisualPrompting from "./VisualPrompting";
import Toggle from "./ui/Toggle";
import Input from "./ui/Input";

const Prompts = ({positivePrompt, setPositivePrompt, negativePrompt, setNegativePrompt}) => {

    const [isVisualPromptingOn, setIsVisualPromptingOn] = useState(false);

    return(
        <>
         {/*Visual prompting*/}
          <div className="flex items-center space-x-3">
            <TextTooltip
                text="Visual prompting"
                tooltip="Enable or disable visual prompting."
              />
            <Toggle
              checked={isVisualPromptingOn}
              onChange={(newValue) => {
                if (newValue) {
                  const proceed = window.confirm(
                    `You are about to turn on Visual Prompting mode. Your positive and negative prompts will be erased! Continue?`
                  );
                  if (proceed) setIsVisualPromptingOn(newValue);
                } else {
                  const proceed = window.confirm(
                    `You are about to turn off Visual Prompting Mode. Your choices will be translated into textual positive and negative prompts. Continue?`
                  );
                  if (proceed) setIsVisualPromptingOn(newValue);
                }
              }}
            />
          </div>
          {isVisualPromptingOn ? (

            <VisualPrompting
              positivePromptSetter={setPositivePrompt}
              negativePromptSetter={setNegativePrompt}
            />

          ) : (
            <>

              <TextTooltip
                text="Positive prompt"
                tooltip="Provide a natural-language description of what the image should contain."
              />
              <Input
                value={positivePrompt}
                onChange={(e) => setPositivePrompt(e.target.value)}
                placeholder="Enter prompt"
              />

              <TextTooltip
                text="Negative prompt"
                tooltip="Provide a natural-language description of what the image should not contain."
              />
              <Input
                value={negativePrompt}
                onChange={(e) => setNegativePrompt(e.target.value)}
                placeholder="Enter negative prompt (optional)"
              />
            </>
          )}
        </>
    )

}

export default Prompts;