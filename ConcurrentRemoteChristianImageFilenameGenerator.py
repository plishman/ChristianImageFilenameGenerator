import asyncio
import time
from pathlib import Path
from openai import AsyncOpenAI
from PIL import Image
import base64
from tqdm.asyncio import tqdm_asyncio
import argparse
import re
import numpy as np
from io import BytesIO
import logging
from tqdm.asyncio import tqdm
from tqdm.asyncio import tqdm_asyncio   # make sure this import is present

# ─── Config ────────────────────────────────────────────────────────────────
SERVER_URL = "https://openrouter.ai/api/v1"
API_KEY = "<please specify your api key in command args>"                   # ← your real key
MODEL = "x-ai/grok-4.1-fast"
FOLDER = r"./images"
BATCH_FILE_NAME = "rename_images.bat"
PROCESSED_LOG_NAME = "processed_images.log"

MAX_FILENAME_WORDS = 7
#SUPPORTED_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
SUPPORTED_EXT = {'.jpg', '.jpeg', '.jfif', '.jpe', '.jfi',   # all JPEG family variants
            '.png',
            '.webp',
            '.bmp',
            '.gif',
            '.tiff', '.tif'}
# Concurrency control
MAX_CONCURRENT = 72          # ← tune this: start low (4–8), increase if stable
REQUEST_TIMEOUT = 90        # seconds

# Sharpness-based resize settings
SHARPNESS_HIGH = 200
SHARPNESS_MED  = 50
MIN_WIDTH = 256
MAX_WIDTH = 1024

PROMPT_TEMPLATE = """You are an expert in Biblical and Traditional Christian imagery, including scenes from the Old and New Testaments, depictions of Jesus Christ, Mary, saints, apostles, angels, demons, miracles, parables, symbols like the cross, ichthys, dove, lamb, or architectural elements like cathedrals, altars, and stained glass in a religious context. Your task is to analyze the provided image and generate a single, concise filename (e.g., "descriptive_name") that accurately describes its content.
First, classify if the image primarily depicts a Biblical event, figure, symbol, or Traditional Christian theme (e.g., Nativity, Crucifixion, Last Supper, saints' lives, sacraments, or ecclesiastical art). If it does, prioritize a filename that directly references the specific Biblical or Christian element, using accurate terminology (e.g., "Jesus_Healing_the_Blind" instead of generic).
If the image does not clearly depict Biblical or Traditional Christian content, check for any subtle or thematic connection (e.g., a garden might relate to "Garden_of_Eden" if fitting, or a shepherd to "Good_Shepherd"). Only apply this if the link is reasonable and enhances accuracy—do not force it.
If no Biblical or Christian connection applies, fall back to a neutral, secular description based on the main subjects, actions, colors, style, or composition (e.g., "(secular) Red_Sports_Car_on_Highway").
For the filename use 5-15 words max, underscore-separated, descriptive nouns/adjectives, no articles/prepositions unless essential, no file extension. Output only the filename—nothing else."""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_sharpness(img: Image.Image) -> float:
    gray = img.convert('L')
    array = np.asarray(gray).astype(float)
    if array.shape[0] < 3 or array.shape[1] < 3:
        return 0.0
    lap = (
        -4.0 * array[1:-1, 1:-1]
        + array[:-2, 1:-1]
        + array[2:, 1:-1]
        + array[1:-1, :-2]
        + array[1:-1, 2:]
    )
    return float(np.var(lap))


def prepare_image_for_model(img_path: Path) -> str:
    img = Image.open(img_path)
    
    # ─── Critical fix: convert to RGB (drop alpha/transparency) ─────────────
    if img.mode in ('RGBA', 'LA', 'P'):           # P can have alpha in some cases
        # Option A: simple discard alpha (black background)
        img = img.convert('RGB')
        
        # Option B: composite on white background (better for most art/icons)
        # background = Image.new('RGB', img.size, (255, 255, 255))
        # img = Image.alpha_composite(background, img.convert('RGBA')).convert('RGB')

    sharpness = get_sharpness(img)   # sharpness now works on RGB
    
    if sharpness > SHARPNESS_HIGH:
        target_width = 512
    elif sharpness > SHARPNESS_MED:
        target_width = 384
    else:
        target_width = MIN_WIDTH
    
    target_width = max(MIN_WIDTH, min(MAX_WIDTH, target_width))
    
    if img.width > target_width:
        ratio = target_width / float(img.width)
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
    
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

async def get_suggested_name(
    client: AsyncOpenAI,
    img_path: Path,
    semaphore: asyncio.Semaphore,
    file_lock: asyncio.Lock
) -> tuple[Path, str | None]:
    async with semaphore:
        try:
            base64_img = await asyncio.to_thread(prepare_image_for_model, img_path)

            response = await client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT_TEMPLATE},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
                            }
                        ]
                    }
                ],
                temperature=0.1,
                max_tokens=60,
                timeout=REQUEST_TIMEOUT,
            )

            content = response.choices[0].message.content
            if not isinstance(content, str):
                return img_path, None

            name = content.strip()

            name = re.sub(r'[^a-z0-9_-]', '', name.lower())
            name = re.sub(r'-+', '-', name).strip('-_')

            if len(name) < 5:
                return img_path, None

            return img_path, name

        except Exception as e:
            logger.error(f"Error processing {img_path.name}: {e}")
            return img_path, None


def escape_batch_filename(name: str) -> str:
    for c in '&%!?^':
        name = name.replace(c, f'^{c}')
    return name


async def append_rename_command(
    batch_path: Path,
    img_path: Path,
    new_name: str,
    file_lock: asyncio.Lock
):
    cmd = f'ren "{img_path.absolute()}" {escape_batch_filename(new_name)}\n'
    async with file_lock:
        with open(batch_path, 'a', encoding='utf-8', errors='replace') as f:
            f.write(cmd)


async def append_processed(
    log_path: Path,
    img_path: Path,
    file_lock: asyncio.Lock
):
    async with file_lock:
        with open(log_path, 'a', encoding='utf-8', errors='replace') as f:
            f.write(f"{img_path.absolute()}\n")


async def process_image(
    client: AsyncOpenAI,
    img_path: Path,
    semaphore: asyncio.Semaphore,
    file_lock: asyncio.Lock,
    batch_file: Path,
    processed_log: Path,
    #pbar: tqdm_asyncio
):
    abs_str = str(img_path.absolute())

    # Quick check if already processed (file lock not needed for read here)
    # Note: this is racy but acceptable; worst case = redundant API call
    if processed_log.exists():
        with open(processed_log, encoding='utf-8', errors='replace') as f:
            if abs_str in {line.strip() for line in f}:
                #pbar.update(1)
                return

    suggested_tuple = await get_suggested_name(client, img_path, semaphore, file_lock)
    _, suggested = suggested_tuple

    if not suggested:
        # Still mark as processed to avoid retry loops
        await append_processed(processed_log, img_path, file_lock)
        #pbar.update(1)
        logger.info(f"  → SKIPPED (no suggestion) {img_path.name}")
        return

    new_name = f"{suggested}{img_path.suffix.lower()}"

    # Collision handling (local to this process; racy across processes but rare)
    counter = 1
    candidate = new_name
    new_path = img_path.with_name(candidate)
    while new_path.exists() and new_path != img_path:
        candidate = f"{suggested}-{counter}{img_path.suffix.lower()}"
        new_path = img_path.with_name(candidate)
        counter += 1

    await append_rename_command(batch_file, img_path, candidate, file_lock)
    await append_processed(processed_log, img_path, file_lock)

    logger.info(f"  → {img_path.name}  →  {candidate}")
    #pbar.update(1)


async def main_async(args):
    client = AsyncOpenAI(base_url=args.server_url, api_key=args.api_key, timeout=REQUEST_TIMEOUT)

    root = Path(args.folder).resolve()
    batch_file = root / args.batch_file_name
    processed_log = root / args.processed_images_log_name

    if args.reset and processed_log.exists():
        logger.info("Reset requested → deleting processed log")
        processed_log.unlink()

    if not batch_file.exists():
        with open(batch_file, 'w', encoding='utf-8') as f:
            f.write("echo Starting rename operations...\n\n")

    images = sorted(p for p in root.rglob("*") if p.suffix.lower() in SUPPORTED_EXT)

    logger.info(f"Found {len(images)} images")
    logger.info(f"Batch file     : {batch_file}")
    logger.info(f"Processed log  : {processed_log}")

    semaphore = asyncio.Semaphore(max(1, args.max_concurrent))
    file_lock = asyncio.Lock()

    # Create tasks (remove pbar from process_image args)
    tasks = [
        process_image(client, img_path, semaphore, file_lock, batch_file, processed_log)
        for img_path in images
    ]

    # Run with tqdm progress
    #await tqdm_asyncio.gather(
    #    *tasks,
    #    total=len(images),
    #    desc="Processing",
    #    unit="img",
    #    leave=True,
    #    return_exceptions=True
    #)

    # In main_async, replace the gather block with:
    pbar = tqdm(total=len(images), desc="Processing", unit="img", leave=True)

    tasks = [
        process_image(client, img_path, semaphore, file_lock, batch_file, processed_log)
        for img_path in images
    ]

    # Run gather normally (with return_exceptions)
    await asyncio.gather(*tasks, return_exceptions=True)

    # Manually update progress (simple version)
    pbar.update(len(images))   # or loop over results if you want per-task updates
    pbar.close()

    logger.info("\nFinished this run.")
    logger.info(f"Batch file: {batch_file}")
    logger.info("Review/edit the .bat file, then run it from cmd/powershell.")

def main():
    global MODEL

    parser = argparse.ArgumentParser(
        description=(
            "Analyze images in a folder with an OpenAI-compatible vision model, "
            "generate suggested Christian-themed filenames, and write rename "
            "commands to a batch file while tracking processed images."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--server-url",
        type=str,
        default=SERVER_URL,
        help="OpenAI-compatible API base URL (e.g., https://openrouter.ai/api/v1).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=API_KEY,
        help="API key used to authenticate requests to the model provider.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=MODEL,
        help="Model identifier used for image-to-filename generation.",
    )
    parser.add_argument(
        "--folder",
        type=str,
        default=FOLDER,
        help="Root folder to scan recursively for supported image files.",
    )
    parser.add_argument(
        "--batch-file-name",
        type=str,
        default=BATCH_FILE_NAME,
        help="Output batch filename that receives generated rename commands.",
    )
    parser.add_argument(
        "--processed-images-log-name",
        "--processed-log-name",
        dest="processed_images_log_name",
        type=str,
        default=PROCESSED_LOG_NAME,
        help="Log filename that stores absolute paths already processed.",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=MAX_CONCURRENT,
        help="Maximum number of concurrent image/model processing tasks.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete processed log before running and process all images from scratch.",
    )
    args = parser.parse_args()

    MODEL = args.model

    masked_api_key = args.api_key
    if masked_api_key:
        if len(masked_api_key) <= 8:
            masked_api_key = "*" * len(masked_api_key)
        else:
            masked_api_key = f"{masked_api_key[:4]}...{masked_api_key[-4:]}"

    logger.info("Program summary:")
    logger.info("  Scans image files in the target folder (recursive).")
    logger.info("  Sends each image to a vision model for a suggested filename.")
    logger.info("  Appends rename commands to a batch file.")
    logger.info("  Tracks processed images to avoid duplicate work.")
    logger.info("Run settings:")
    logger.info(f"  server_url={args.server_url}")
    logger.info(f"  api_key={masked_api_key}")
    logger.info(f"  model={args.model}")
    logger.info(f"  folder={Path(args.folder).resolve()}")
    logger.info(f"  batch_file_name={args.batch_file_name}")
    logger.info(f"  processed_images_log_name={args.processed_images_log_name}")
    logger.info(f"  max_concurrent={max(1, args.max_concurrent)}")
    logger.info(f"  reset={args.reset}")

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()