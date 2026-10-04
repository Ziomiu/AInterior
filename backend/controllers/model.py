import os
import json
import asyncio
import contextlib
import logging
import uuid
import torch
import httpx
from PIL import Image, ImageOps
from dotenv import load_dotenv

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from huggingface_hub import login

from utils.auth_helpers import get_current_user
from utils import gpu_queue
from utils.saving_images_helpers import image_to_string, string_to_image, save_image_record
from schemas.generation import TextToImageRequest, Img2ImgRequest, ControlNetRequest, Inpainting, Outpainting

models= APIRouter()
logger = logging.getLogger(__name__)

COMFYUI_URL = os.getenv("COMFYUI_URL", "http://comfyui:8188").rstrip("/")
COMFYUI_QUEUE_TIMEOUT_SECONDS = 20.0
COMFYUI_REQUEST_TIMEOUT_SECONDS = 10.0
COMFYUI_GENERATION_TIMEOUT_SECONDS = 180.0

model_versions = {
    '1.5' : 'stable-diffusion-1-5.safetensors',
    '1.5-inpainting' : 'sd-v1-5-inpainting.safetensors',
    '2.0-inpainting' : '512-inpainting-ema.safetensors',
    '2.1' : 'stable-diffusion-2-1.ckpt',
    '3.0' : 'stable-diffusion-3-medium.safetensors',
    'xl' : 'stable-diffusion-xl.safetensors',
    'xl-inpainting' : 'sd_xl_base_1.0_inpainting_0.1.safetensors',
    'controlnet' : 'dreamCreationVirtual3DECommerce_v10.safetensors',
    'juggernaut-inpainting' : 'juggernaut-inpainting.safetensors',
}

model_version_to_input_size = {
    '1.5' : (512,512),
    '1.5-inpainting' : (512,512),
    '2.0-inpainting' : (512,512),
    '2.1' : (768,768),
    '3.0' : (1024,1024),
    'xl' : (1024,1024),
    'xl-inpainting' : (1024,1024),
    'controlnet' : (512,512),
    'juggernaut-inpainting' : (1024,1024),
}

model_version_to_megapixels = {
    '1.5': 0.262,
    '2.1': 0.589,
    '3.0': 1.048,
    'xl': 1.048,
    '1.5-inpainting' :  0.262,
    '2.0-inpainting' :  0.589,
    'xl-inpainting' : 1.048,
    'controlnet': 0.262,
}


class ComfyUIExecutionUncertain(Exception):
    pass


async def _get_comfyui_image(prompt_json):
    queue_payload = {'prompt': prompt_json}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(COMFYUI_REQUEST_TIMEOUT_SECONDS, connect=3.0)
    ) as client:
        try:
            queue_response = await asyncio.wait_for(
                client.post(f'{COMFYUI_URL}/prompt', json=queue_payload),
                timeout=COMFYUI_QUEUE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as error:
            raise ComfyUIExecutionUncertain('Timed out queueing prompt.') from error
        except httpx.RequestError as error:
            raise ComfyUIExecutionUncertain('Unable to determine whether ComfyUI accepted the prompt.') from error

        if not queue_response.is_success:
            if queue_response.status_code >= 500:
                raise ComfyUIExecutionUncertain('ComfyUI returned an uncertain queueing error.')
            raise HTTPException(status_code=502, detail='Error queueing prompt')

        try:
            queue_response_json = queue_response.json()
        except ValueError as error:
            raise ComfyUIExecutionUncertain('ComfyUI returned an invalid queue response.') from error

        if 'prompt_id' not in queue_response_json:
            raise ComfyUIExecutionUncertain('ComfyUI response did not include a prompt_id.')

        prompt_id = queue_response_json['prompt_id']
        loop = asyncio.get_running_loop()
        deadline = loop.time() + COMFYUI_GENERATION_TIMEOUT_SECONDS

        image_response_json = None
        while loop.time() < deadline:
            remaining = deadline - loop.time()
            try:
                image_response = await asyncio.wait_for(
                    client.get(f'{COMFYUI_URL}/history/{prompt_id}'),
                    timeout=min(COMFYUI_REQUEST_TIMEOUT_SECONDS, remaining),
                )
            except asyncio.TimeoutError:
                continue
            except httpx.RequestError:
                await asyncio.sleep(min(1.0, max(0.0, deadline - loop.time())))
                continue

            if image_response.is_success:
                try:
                    image_response_json = image_response.json()
                except ValueError:
                    image_response_json = None
                if prompt_id in (image_response_json or {}):
                    break
            await asyncio.sleep(min(1.0, max(0.0, deadline - loop.time())))
        else:
            raise ComfyUIExecutionUncertain('Timed out waiting for ComfyUI; GPU slot remains blocked until checked.')
     
        outputs = image_response_json[prompt_id].get('outputs', {})
        if not outputs:
            raise HTTPException(status_code=404, detail='No outputs found in workflow response')

        filename = None
        for node_output in outputs.values():
            if 'images' in node_output and len(node_output['images']) > 0:
                filename = node_output['images'][0]['filename']
                break

        if not filename:
            raise HTTPException(status_code=404, detail='No image output found in workflow response')
    
        image_path = os.path.join('output_images', filename)
    
        if not os.path.exists(image_path):
            raise HTTPException(status_code=404, detail=f"Image file {image_path} not found")

        def encode_image():
            with Image.open(image_path) as image:
                return image_to_string(image)

        return await asyncio.to_thread(encode_image)


_background_generations: set[asyncio.Task] = set()


async def _generate_with_gpu_slot(prompt_json, user_id: str, operation: str):
    try:
        ticket_id = await gpu_queue.enqueue(user_id, f"comfyui:{operation}")
    except gpu_queue.QueueFullError as error:
        raise HTTPException(status_code=429, detail=str(error), headers={"Retry-After": "30"}) from error

    claim_id = uuid.uuid4().hex
    try:
        await gpu_queue.acquire(ticket_id, claim_id)
    except asyncio.CancelledError:
        await _abandon_gpu_ticket(ticket_id, claim_id, "request cancelled while waiting")
        raise
    except TimeoutError as error:
        await gpu_queue.cancel(ticket_id, "queue_wait_timeout")
        raise HTTPException(status_code=504, detail="Timed out waiting for the shared GPU queue") from error
    except Exception as error:
        await gpu_queue.cancel(ticket_id, "queue_acquire_failed")
        raise HTTPException(status_code=503, detail="Shared GPU queue is unavailable") from error

    heartbeat_task = asyncio.create_task(_gpu_heartbeat(ticket_id, claim_id))
    try:
        image = await _get_comfyui_image(prompt_json)
    except ComfyUIExecutionUncertain as error:
        try:
            await gpu_queue.mark_stalled(ticket_id, claim_id, str(error))
        except Exception:
            logger.exception("Could not mark uncertain ComfyUI job as stalled")
        raise HTTPException(status_code=504, detail=str(error)) from error
    except asyncio.CancelledError:
        await _abandon_gpu_ticket(ticket_id, claim_id, "request cancelled during ComfyUI inference")
        raise
    except Exception:
        await gpu_queue.release(ticket_id, claim_id, "failed")
        raise
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task

    await gpu_queue.release(ticket_id, claim_id, "done")
    return image


async def _gpu_heartbeat(ticket_id: str, claim_id: str):
    while True:
        await asyncio.sleep(5)
        try:
            await gpu_queue.heartbeat(ticket_id, claim_id)
        except Exception:
            logger.exception("GPU queue heartbeat failed for ticket %s", ticket_id)


async def _abandon_gpu_ticket(ticket_id: str, claim_id: str, reason: str):
    try:
        current = await gpu_queue.status(ticket_id)
        if current and current.get("claim_id") == claim_id:
            await gpu_queue.mark_stalled(ticket_id, claim_id, reason)
        else:
            await gpu_queue.cancel(ticket_id, "request_cancelled")
    except Exception:
        logger.exception("Could not safely clean up GPU ticket %s", ticket_id)


async def get_image(prompt_json, user_id=None, operation="generation"):
    if user_id is None:
        try:
            return await _get_comfyui_image(prompt_json)
        except ComfyUIExecutionUncertain as error:
            raise HTTPException(status_code=504, detail=str(error)) from error

    task = asyncio.create_task(_generate_with_gpu_slot(prompt_json, str(user_id), operation))
    _background_generations.add(task)
    task.add_done_callback(_background_generations.discard)
    return await asyncio.shield(task)

@models.post('/generate/text-to-image')
async def text_to_image(textToImageRequest: TextToImageRequest, current_user: dict = Depends(get_current_user)):
    if textToImageRequest.model_version not in model_versions:
        raise HTTPException(status_code=404, detail='Model version does not exist.')
    
    txt2img_path = os.path.join('workflows_api', 'txt2img.json')
    
    if not os.path.exists(txt2img_path):
        raise HTTPException(status_code=404, detail='File not found')

    prompt_json = {}
    
    with open(txt2img_path, 'r') as f:
        prompt_json = json.load(f)
    
    prompt_json['4']['inputs']['ckpt_name'] = model_versions[textToImageRequest.model_version]
    
    prompt_json['3']['inputs']['seed'] = textToImageRequest.seed
    prompt_json['3']['inputs']['steps'] = 30
    prompt_json['3']['inputs']['cfg'] = textToImageRequest.guidance_scale
    
    prompt_json['5']['inputs']['width'] = textToImageRequest.width
    prompt_json['5']['inputs']['height'] = textToImageRequest.height    
    prompt_json['5']['inputs']['barch_size'] = 1
    
    prompt_json['6']['inputs']['text'] = textToImageRequest.prompt
    prompt_json['7']['inputs']['text'] = textToImageRequest.negative_prompt    
    
    image_base64 = await get_image(prompt_json, current_user["_id"], "text-to-image")
            
    await save_image_record(
        user_id=str(current_user["_id"]),
        image_base64=image_base64,
        metadata={
            "model": textToImageRequest.model_version,
            "mode": "text2img",
            "prompt": textToImageRequest.prompt,
            "negative_prompt": textToImageRequest.negative_prompt,
            "guidance_scale": textToImageRequest.guidance_scale,
            "width": textToImageRequest.width,
            "height": textToImageRequest.height,
            "seed": textToImageRequest.seed
        }
    )

    return JSONResponse(content={"image": image_base64})
    
    
@models.post('/generate/image-to-image')
async def edit_image(img2ImgRequest: Img2ImgRequest, current_user: dict = Depends(get_current_user)):
    if img2ImgRequest.model_version not in model_versions:
        raise HTTPException(status_code=404, detail='Model version does not exist.')
    
    img2img_path = os.path.join('workflows_api', 'img2img.json')
    
    if not os.path.exists(img2img_path):
        raise HTTPException(status_code=404, detail='File not found')
    
    prompt_json = {}
    
    with open(img2img_path, 'r') as f:
        prompt_json = json.load(f)
        
    image = string_to_image(img2ImgRequest.image)
    image_width, image_height = image.size
    image_name = f'{uuid.uuid4()}.png'
    image.save(os.path.join('input_images', image_name))
    
    prompt_json['14']['inputs']['ckpt_name'] = model_versions[img2ImgRequest.model_version]
    
    prompt_json['10']['inputs']['image'] = image_name
    
    if img2ImgRequest.scaling_mode == 'resize_and_pad':
        prompt_json['20']['inputs']['target_width'] = model_version_to_input_size[img2ImgRequest.model_version][0]
        prompt_json['20']['inputs']['target_height'] = model_version_to_input_size[img2ImgRequest.model_version][1]
        prompt_json['12']['inputs']['pixels'][0]='20'
    elif img2ImgRequest.scaling_mode == 'scale_to_megapixels':
        prompt_json['21']['inputs']['megapixels'] = model_version_to_megapixels[img2ImgRequest.model_version]
        prompt_json['12']['inputs']['pixels'][0]='21'
    else:
        prompt_json['12']['inputs']['pixels'][0]='10'

    prompt_json['3']['inputs']['seed'] = img2ImgRequest.seed
    prompt_json['3']['inputs']['steps'] = 30
    prompt_json['3']['inputs']['cfg'] = img2ImgRequest.guidance_scale
    
    prompt_json['6']['inputs']['text'] = img2ImgRequest.prompt
    prompt_json['7']['inputs']['text'] = img2ImgRequest.negative_prompt    
    
    image_base64 = await get_image(prompt_json, current_user["_id"], "image-to-image")

    await save_image_record(
        user_id=str(current_user["_id"]),
        image_base64=image_base64,
        metadata={
            "model": img2ImgRequest.model_version,
            "mode": "text2img",
            "prompt": img2ImgRequest.prompt,
            "negative_prompt": img2ImgRequest.negative_prompt,
            "guidance_scale": img2ImgRequest.guidance_scale,
            "width": image_width,
            "height": image_height,
            "seed": img2ImgRequest.seed,
            "scaling_mode": img2ImgRequest.scaling_mode,
        }
    )

    return JSONResponse(content={"image": image_base64})
    

@models.post('/generate/control-net')
async def control_net(controlNetRequest: ControlNetRequest, current_user: dict = Depends(get_current_user)):
    if controlNetRequest.model_version not in model_versions:
        raise HTTPException(status_code=404, detail='Model version does not exist.')
    
    img2img_path = os.path.join('workflows_api', 'controlnet.json')
    
    if not os.path.exists(img2img_path):
        raise HTTPException(status_code=404, detail='File not found')
    
    prompt_json = {}
    
    with open(img2img_path, 'r') as f:
        prompt_json = json.load(f)
        
    image = string_to_image(controlNetRequest.image)
    image_width, image_height = image.size
    image_name = f'{uuid.uuid4()}.png'
    image.save(os.path.join('input_images', image_name))
        
    prompt_json['14']['inputs']['ckpt_name'] = model_versions[controlNetRequest.model_version]
    
    prompt_json['40']['inputs']['image'] = image_name
    
    if controlNetRequest.scaling_mode == 'resize_and_pad':
        prompt_json['33']['inputs']['target_width'] = model_version_to_input_size[controlNetRequest.model_version][0]
        prompt_json['33']['inputs']['target_height'] = model_version_to_input_size[controlNetRequest.model_version][1]
        prompt_json['35']['inputs']['image'][0]='33'
    elif controlNetRequest.scaling_mode == 'scale_to_megapixels':
        prompt_json['37']['inputs']['megapixels'] = model_version_to_megapixels[controlNetRequest.model_version]
        prompt_json['35']['inputs']['image'][0]='37'
    else:
        prompt_json['35']['inputs']['image'][0]='11'
    
    prompt_json['35']['inputs']['low_threshold'] = controlNetRequest.cannyLowThreshold
    prompt_json['35']['inputs']['high_threshold'] = controlNetRequest.cannyHighThreshold
    
    prompt_json['3']['inputs']['seed'] = controlNetRequest.seed
    prompt_json['3']['inputs']['steps'] = 30
    prompt_json['3']['inputs']['cfg'] = controlNetRequest.guidance_scale
    
    prompt_json['6']['inputs']['text'] = controlNetRequest.prompt
    prompt_json['7']['inputs']['text'] = controlNetRequest.negative_prompt    
    
    image_base64 = await get_image(prompt_json, current_user["_id"], "control-net")

    await save_image_record(
        user_id=str(current_user["_id"]),
        image_base64=image_base64,
        metadata={
            "model": controlNetRequest.model_version,
            "mode": "controlnet",
            "prompt": controlNetRequest.prompt,
            "negative_prompt": controlNetRequest.negative_prompt,
            "guidance_scale": controlNetRequest.guidance_scale,
            "canny_low_threshold": controlNetRequest.cannyLowThreshold,
            "canny_high_threshold": controlNetRequest.cannyHighThreshold,
            "width": image_width,
            "height": image_height,
            "seed": controlNetRequest.seed,
            "scaling_mode": controlNetRequest.scaling_mode,
        }
    )

    return JSONResponse(content={"image": image_base64})
    
    
@models.post('/generate/inpainting')
async def image_inpainting(inpainting: Inpainting, current_user: dict = Depends(get_current_user)):
    if inpainting.model_version not in model_versions:
        raise HTTPException(status_code=404, detail='Model version does not exist.')
    
    inpainting_path = os.path.join('workflows_api', 'inpainting.json')
    
    if not os.path.exists(inpainting_path):
        raise HTTPException(status_code=404, detail='File not found')
    
    prompt_json = {}
    
    with open(inpainting_path, 'r') as f:
        prompt_json = json.load(f)
        
    image = string_to_image(inpainting.image)
    mask = string_to_image(inpainting.mask_image)
    
    mask = mask.crop((0, 0, image.width, image.height))
    
    if image.size != mask.size:
        raise HTTPException(status_code=404, detail="Image size and mask size don't match!")
    
    image_width, image_height = image.size
    
    image_name = f'{uuid.uuid4()}.png'
    mask_name = f'{uuid.uuid4()}.png'
    
    image.save(os.path.join('input_images', image_name))
    mask.save(os.path.join('input_images', mask_name))

    prompt_json['29']['inputs']['ckpt_name'] = model_versions[inpainting.model_version]
    
    prompt_json['20']['inputs']['image'] = image_name
    prompt_json['37']['inputs']['image'] = mask_name
    
    prompt_json['66']['inputs']['output_target_width'] = model_version_to_input_size[inpainting.model_version][0]
    prompt_json['66']['inputs']['output_target_height'] = model_version_to_input_size[inpainting.model_version][1]
    
    prompt_json['3']['inputs']['seed'] = inpainting.seed
    prompt_json['3']['inputs']['cfg'] = inpainting.guidance_scale
    
    prompt_json['6']['inputs']['text'] = inpainting.prompt
    prompt_json['7']['inputs']['text'] = inpainting.negative_prompt
    
    image_base64 = await get_image(prompt_json, current_user["_id"], "inpainting")
    
    try:
        await save_image_record(
            user_id=str(current_user["_id"]),
            image_base64=image_base64,
            metadata={
                "model": inpainting.model_version,
                "mode": "inpainting",
                "prompt": inpainting.prompt,
                "negative_prompt": inpainting.negative_prompt,
                "guidance_scale": inpainting.guidance_scale,
                "seed": inpainting.seed,
                "width": image_width,
                "height": image_height,
            }
        )
        print("Image record saved successfully")
    except Exception as e:
        print("Error saving image record:", e)
        raise HTTPException(status_code=500, detail=f"Failed to save image record: {e}")

    return JSONResponse(content={"image": image_base64})


@models.post('/generate/outpainting')
async def image_outpainting(outpainting: Outpainting, current_user: dict = Depends(get_current_user)):
    if outpainting.model_version not in model_versions:
        raise HTTPException(status_code=404, detail='Model version does not exist.')
    
    outpainting_path = os.path.join('workflows_api', 'outpainting.json')
    
    if not os.path.exists(outpainting_path):
        raise HTTPException(status_code=404, detail='File not found')
    
    prompt_json = {}
    
    with open(outpainting_path, 'r') as f:
        prompt_json = json.load(f)
        
    image = string_to_image(outpainting.image)
    
    image_width, image_height = image.size
    
    image_name = f'{uuid.uuid4()}.png'
    
    image.save(os.path.join('input_images', image_name))

    prompt_json['29']['inputs']['ckpt_name'] = model_versions[outpainting.model_version]

    prompt_json['20']['inputs']['image'] = image_name

    if outpainting.scaling_mode == 'resize_and_pad':
        prompt_json['40']['inputs']['target_width'] = model_version_to_input_size[outpainting.model_version][0]
        prompt_json['40']['inputs']['target_height'] = model_version_to_input_size[outpainting.model_version][1]
        prompt_json['30']['inputs']['image'][0] = '40'
    elif outpainting.scaling_mode == 'scale_to_megapixels':
        prompt_json['41']['inputs']['megapixels'] = model_version_to_megapixels[outpainting.model_version]
        prompt_json['30']['inputs']['image'][0] = '41'
    else:
        prompt_json['30']['inputs']['image'][0] = '20'
    
    prompt_json['3']['inputs']['seed'] = outpainting.seed
    prompt_json['3']['inputs']['cfg'] = outpainting.guidance_scale
    
    prompt_json['30']['inputs']['left'] = outpainting.pad_left
    prompt_json['30']['inputs']['right'] = outpainting.pad_right
    prompt_json['30']['inputs']['top'] = outpainting.pad_top
    prompt_json['30']['inputs']['bottom'] = outpainting.pad_bottom
    
    prompt_json['6']['inputs']['text'] = outpainting.prompt
    prompt_json['7']['inputs']['text'] = outpainting.negative_prompt
    
    image_base64 = await get_image(prompt_json, current_user["_id"], "outpainting")
    
    try:
        await save_image_record(
            user_id=str(current_user["_id"]),
            image_base64=image_base64,
            metadata={
                "model": outpainting.model_version,
                "mode": "outpainting",
                "prompt": outpainting.prompt,
                "negative_prompt": outpainting.negative_prompt,
                "guidance_scale": outpainting.guidance_scale,
                "seed": outpainting.seed,
                'pad_right': outpainting.pad_right,
                'pad_left': outpainting.pad_left,
                'pad_top': outpainting.pad_top,
                'pad_bottom': outpainting.pad_bottom,
                "width": image_width,
                "height": image_height,
                "scaling_mode": outpainting.scaling_mode,
            }
        )
        print("Image record saved successfully")
    except Exception as e:
        print("Error saving image record:", e)
        raise HTTPException(status_code=500, detail=f"Failed to save image record: {e}")

    return JSONResponse(content={"image": image_base64})