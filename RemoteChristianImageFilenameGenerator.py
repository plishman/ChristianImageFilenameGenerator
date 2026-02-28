import os
import time
from pathlib import Path
from openai import OpenAI
from PIL import Image
import base64
from tqdm import tqdm
import argparse
import re
import numpy as np
from io import BytesIO

# ─── Config ────────────────────────────────────────────────────────────────
SERVER_URL = "https://openrouter.ai/api/v1"
API_KEY = "<please specify your api key in command args>"                   # ← your real key
MODEL = "x-ai/grok-4.1-fast"
FOLDER = r"./images"                         # ← change this
BATCH_FILE_NAME = "rename_images.bat"
PROCESSED_LOG_NAME = "processed_images.log"  # one absolute path per line

MAX_FILENAME_WORDS = 7
#SUPPORTED_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
SUPPORTED_EXT = {'.jpg', '.jpeg', '.jfif', '.jpe', '.jfi',   # all JPEG family variants
            '.png',
            '.webp',
            '.bmp',
            '.gif',
            '.tiff', '.tif'}


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


def get_sharpness(img: Image.Image) -> float:
    gray = img.convert('L')
    array = np.asarray(gray).astype(float)
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


def get_suggested_name(client: OpenAI, img_path: Path) -> str | None:
    try:
        base64_img = prepare_image_for_model(img_path)

        response = client.chat.completions.create(
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
        )

        content = response.choices[0].message.content
        if not isinstance(content, str):
            return None

        name = content.strip()
        name = re.sub(r'[^a-z0-9_-]', '', name.lower())
        name = re.sub(r'-+', '-', name).strip('-_')

        if len(name) < 5:
            return None

        return name
    except Exception as e:
        print(f"Error processing {img_path.name}: {e}")
        return None


def escape_batch_filename(name: str) -> str:
    for c in '&%!?^':
        name = name.replace(c, f'^{c}')
    return name


def append_rename_command(batch_path: Path, old_path: Path, new_name: str):
    old_full = str(old_path.absolute())
    cmd = f'ren "{old_full}" {escape_batch_filename(new_name)}\n'
    with open(batch_path, 'a', encoding='utf-8', errors='replace') as f:
        f.write(cmd)


def load_processed_set(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    with open(log_path, encoding='utf-8', errors='replace') as f:
        return {line.strip() for line in f if line.strip()}


def append_processed(log_path: Path, img_path: Path):
    with open(log_path, 'a', encoding='utf-8', errors='replace') as f:
        f.write(f"{img_path.absolute()}\n")


def main():
    global MODEL

    parser = argparse.ArgumentParser(
        description=(
            "Scan images in a folder, ask an OpenAI-compatible vision model for "
            "filename suggestions, write rename commands to a batch file, and "
            "track already-processed images for resumable runs."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--server-url",
        type=str,
        default=SERVER_URL,
        help="OpenAI-compatible API base URL.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=API_KEY,
        help="API key used to authenticate model requests.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=MODEL,
        help="Model identifier for image-to-filename generation.",
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
        help="Log filename storing absolute paths already processed.",
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

    print("Program summary:")
    print("  Scans image files in the target folder (recursive).")
    print("  Sends each image to a vision model for a suggested filename.")
    print("  Appends rename commands to a batch file.")
    print("  Tracks processed images to avoid duplicate work.")
    print("Run settings:")
    print(f"  server_url={args.server_url}")
    print(f"  api_key={masked_api_key}")
    print(f"  model={args.model}")
    print(f"  folder={Path(args.folder).resolve()}")
    print(f"  batch_file_name={args.batch_file_name}")
    print(f"  processed_images_log_name={args.processed_images_log_name}")
    print(f"  reset={args.reset}")

    client = OpenAI(base_url=args.server_url, api_key=args.api_key)

    root = Path(args.folder).resolve()
    batch_file = root / args.batch_file_name
    processed_log = root / args.processed_images_log_name

    # ─── Resume / reset logic ──────────────────────────────────────────────
    if args.reset and processed_log.exists():
        print("Reset requested → deleting processed log")
        processed_log.unlink()

    already_processed = load_processed_set(processed_log)
    print(f"Already processed files (from log): {len(already_processed)}")

    # Optional: reset batch file on --reset (uncomment if desired)
    # if args.reset and batch_file.exists():
    #     batch_file.unlink()

    if not batch_file.exists():
        with open(batch_file, 'w', encoding='utf-8') as f:
            f.write("echo Starting rename operations...\n\n")

    images = sorted(p for p in root.rglob("*") if p.suffix.lower() in SUPPORTED_EXT)
    # ^ sorted() gives more stable/reproducible order across runs

    print(f"Found {len(images)} images in total")
    print(f"Will process {len(images) - len(already_processed & {str(p) for p in images})} new/remaining images")
    print(f"Batch file  : {batch_file}")
    print(f"Processed log: {processed_log}")

    processed_count = 0
    skipped_count = 0
    generated = 0

    for img_path in tqdm(images, desc="Processing"):
        abs_path_str = str(img_path.absolute())

        if abs_path_str in already_processed:
            skipped_count += 1
            continue

        suggested = get_suggested_name(client, img_path)
        if not suggested:
            print(f"    → SKIPPED (no suggestion) {img_path.name}")
            # You may still want to mark as processed so we don't retry forever
            append_processed(processed_log, img_path)
            processed_count += 1
            continue

        new_name = f"{suggested}{img_path.suffix.lower()}"

        # Collision handling
        counter = 1
        candidate = new_name
        new_path = img_path.with_name(candidate)
        while new_path.exists() and new_path != img_path:
            candidate = f"{suggested}-{counter}{img_path.suffix.lower()}"
            new_path = img_path.with_name(candidate)
            counter += 1

        # Write rename command
        append_rename_command(batch_file, img_path, candidate)
        generated += 1

        # Mark as done
        append_processed(processed_log, img_path)
        processed_count += 1

        print(f"  → {img_path.name}  →  {candidate}")
        time.sleep(0.3)  # gentle cooldown

    print("\nFinished this run.")
    print(f"  Already processed (skipped) : {skipped_count}")
    print(f"  Commands generated this run : {generated}")
    print(f"  Newly processed this run     : {processed_count}")
    print(f"Batch file     : {batch_file}")
    print(f"Processed log  : {processed_log}")
    print("\nRun again to continue from where it left off (or use --reset to start over).")


if __name__ == "__main__":
    main()