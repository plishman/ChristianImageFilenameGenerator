# watch_and_rename.py
import argparse
import time
import logging
from pathlib import Path
from openai import AsyncOpenAI
import asyncio
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
from PIL import Image
import base64
from io import BytesIO
import re
import numpy as np
from datetime import datetime, timezone

loop = None  # will be set in main()

# ─── Config ────────────────────────────────────────────────────────────────
WATCH_FOLDER = r".\watcher_dropzone"
OUTPUT_FOLDER  = r".\images"
LOG_FILE     = Path(WATCH_FOLDER).parent / "moves_log.txt"
PROCESSED_LOG = Path(WATCH_FOLDER).parent / "processed_log.txt"

SERVER_URL = "https://openrouter.ai/api/v1"
API_KEY = "<please specify your api key in command args>" 
MODEL = "x-ai/grok-4.1-fast"

REQUEST_TIMEOUT = 90
MAX_CONCURRENT = 10
DEBOUNCE_SECONDS = 7.0

# Sharpness settings
SHARPNESS_HIGH = 200
SHARPNESS_MED  = 50
MIN_WIDTH = 256
MAX_WIDTH = 1024

PROMPT_TEMPLATE = """You are an expert in Biblical and Traditional Christian imagery, including scenes from the Old and New Testaments, depictions of Jesus Christ, Mary, saints, apostles, angels, demons, miracles, parables, symbols like the cross, ichthys, dove, lamb, or architectural elements like cathedrals, altars, and stained glass in a religious context. Your task is to analyze the provided image and generate a single, concise filename (e.g., "descriptive_name") that accurately describes its content.
First, classify if the image primarily depicts a Biblical event, figure, symbol, or Traditional Christian theme (e.g., Nativity, Crucifixion, Last Supper, saints' lives, sacraments, or ecclesiastical art). If it does, prioritize a filename that directly references the specific Biblical or Christian element, using accurate terminology (e.g., "Jesus_Healing_the_Blind" instead of generic).
If the image does not clearly depict Biblical or Traditional Christian content, check for any subtle or thematic connection (e.g., a garden might relate to "Garden_of_Eden" if fitting, or a shepherd to "Good_Shepherd"). Only apply this if the link is reasonable and enhances accuracy—do not force it.
If no Biblical or Christian connection applies, fall back to a neutral, secular description based on the main subjects, actions, colors, style, or composition (e.g., "(secular) Red_Sports_Car_on_Highway").
For the filename use 5-15 words max, underscore-separated, descriptive nouns/adjectives, no articles/prepositions unless essential, no file extension. Output only the filename—nothing else."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch a folder and rename Christian images using an LLM.")
    parser.add_argument("--watch-folder", type=str, default=WATCH_FOLDER, help="Input/watch folder path")
    parser.add_argument("--output-folder", type=str, default=OUTPUT_FOLDER, help="Output folder path")
    parser.add_argument("--log-file", type=str, default=None, help="Moves log file path")
    parser.add_argument("--processed-log", type=str, default=None, help="Processed/fingerprint log file path")
    parser.add_argument("--server-url", type=str, default=SERVER_URL, help="OpenAI-compatible server base URL")
    parser.add_argument("--api-key", type=str, default=API_KEY, help="API key")
    parser.add_argument("--model", type=str, default=MODEL, help="Model name")
    parser.add_argument("--max-concurrent", type=int, default=MAX_CONCURRENT, help="Maximum concurrent worker/API operations")
    return parser.parse_args()

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

# ─── Globals ───────────────────────────────────────────────────────────────
API_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT)
file_queue = asyncio.Queue()
recent_events = {}  # str(path) → last seen datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── Helpers (unchanged except for clarity) ───────────────────────────────
def is_image_file(path: Path) -> bool:
    #return path.is_file() and path.suffix.lower() in {'.jpg', '.jpeg', '.jfif', '.png', '.webp', '.bmp', '.gif', '.tiff'}
    return path.is_file() and path.suffix.lower() in {
            '.jpg', '.jpeg', '.jfif', '.jpe', '.jfi',   # all JPEG family variants
            '.png',
            '.webp',
            '.bmp',
            '.gif',
            '.tiff', '.tif'
    }
def get_file_fingerprint(path: Path) -> str | None:
    try:
        stat = path.stat()
        return f"{path.name}|{stat.st_mtime:.6f}|{stat.st_size}"
    except Exception:
        return None

def was_already_processed(path: Path) -> bool:
    fp = get_file_fingerprint(path)
    if not fp or not PROCESSED_LOG.exists():
        return False
    with open(PROCESSED_LOG, encoding='utf-8', errors='replace') as f:
        return fp in {line.strip() for line in f if line.strip()}

def mark_as_processed(path: Path):
    fp = get_file_fingerprint(path)
    if fp:
        with open(PROCESSED_LOG, 'a', encoding='utf-8', errors='replace') as f:
            f.write(f"{fp}\n")

def wait_for_file_stable(path: Path, timeout=30, interval=1.0):
    start = time.time()
    prev_size = -1
    while time.time() - start < timeout:
        try:
            curr = path.stat().st_size
            if curr == prev_size and curr > 0:
                return
            prev_size = curr
            time.sleep(interval)
        except Exception:
            time.sleep(interval)
    logger.warning(f"Timeout waiting for {path.name}")

def log_success(old: Path, new: Path):
    try:
        stat = old.stat()  # called BEFORE rename
        file_time_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        ts = file_time_utc.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} | {old} → {new}\n"
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line)
        logger.info(f"Logged: {old.name} → {new.name} ({ts})")
    except Exception as e:
        logger.warning(f"Log failed for {old.name}: {e}")
        fallback = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{fallback} | {old} → {new}  (timestamp unavailable)\n")

# ─── Model call ────────────────────────────────────────────────────────────
async def get_suggested_name(client: AsyncOpenAI, img_path: Path) -> str | None:
    try:
        base64_img = prepare_image_for_model(img_path)
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": PROMPT_TEMPLATE},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]}
            ],
            temperature=0.1,
            max_tokens=60,
            timeout=REQUEST_TIMEOUT,
        )

        content = response.choices[0].message.content
        if not isinstance(content, str):
            return None

        name = content.strip()
        name = re.sub(r'[^a-z0-9_-]', '', name.lower())
        name = re.sub(r'-+', '-', name).strip('-_')
        return name if len(name) >= 5 else None
    except Exception as e:
        logger.error(f"Model call failed for {img_path.name}: {e}")
        return None

# ─── Worker ────────────────────────────────────────────────────────────────
async def file_worker(client: AsyncOpenAI):
    while True:
        img_path = await file_queue.get()
        if img_path is None:
            file_queue.task_done()
            break

        path_str = str(img_path)
        now = datetime.now()

        if path_str in recent_events:
            if (now - recent_events[path_str]).total_seconds() < DEBOUNCE_SECONDS:
                logger.debug(f"Debounced: {img_path.name}")
                file_queue.task_done()
                continue

        recent_events[path_str] = now

        async with API_SEMAPHORE:
            try:
                await asyncio.to_thread(wait_for_file_stable, img_path)

                if was_already_processed(img_path):
                    logger.info(f"Already processed: {img_path.name}")
                    file_queue.task_done()
                    continue

                suggested = await get_suggested_name(client, img_path)
                if not suggested:
                    logger.warning(f"No suggestion: {img_path.name}")
                    await asyncio.to_thread(mark_as_processed, img_path)
                    file_queue.task_done()
                    continue

                base = suggested
                ext = img_path.suffix.lower()
                counter = 2
                cand_name = f"{base}{ext}"
                cand_path = Path(OUTPUT_FOLDER) / cand_name

                while cand_path.exists():
                    cand_name = f"{base} ({counter}){ext}"
                    cand_path = Path(OUTPUT_FOLDER) / cand_name
                    counter += 1

                # Log BEFORE rename
                await asyncio.to_thread(log_success, img_path, cand_path)

                # Rename / move
                await asyncio.to_thread(img_path.rename, cand_path)

                logger.info(f"Moved: {img_path.name} → {cand_path.name}")

                await asyncio.to_thread(mark_as_processed, img_path)

            except Exception as e:
                logger.error(f"Failed {img_path.name}: {e}")

        file_queue.task_done()

# ─── Handler ───────────────────────────────────────────────────────────────
class ImageHandler(FileSystemEventHandler):
    def on_created(self, event):
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            p = Path(str(event.src_path))
            if is_image_file(p):
                if loop is not None:
                    asyncio.run_coroutine_threadsafe(file_queue.put(p), loop)
                else:
                    logger.warning("Event loop not initialized yet")

    def on_modified(self, event):
        if not event.is_directory:
            p = Path(str(event.src_path))
            if is_image_file(p):
                if loop is not None:
                    asyncio.run_coroutine_threadsafe(file_queue.put(p), loop)
                else:
                    logger.warning("Event loop not initialized yet")

async def periodic_scanner():
    known = set()
    while True:
        await asyncio.sleep(5.0)
        try:
            for p in Path(WATCH_FOLDER).iterdir():
                if is_image_file(p) and p not in known:
                    if not was_already_processed(p):
                        await file_queue.put(p)
                        known.add(p)
        except Exception:
            pass

# ─── Main ──────────────────────────────────────────────────────────────────
def main():
    global loop, WATCH_FOLDER, OUTPUT_FOLDER, LOG_FILE, PROCESSED_LOG, SERVER_URL, API_KEY, MODEL, MAX_CONCURRENT, API_SEMAPHORE

    args = parse_args()

    WATCH_FOLDER = args.watch_folder
    OUTPUT_FOLDER = args.output_folder
    LOG_FILE = Path(args.log_file) if args.log_file else (Path(WATCH_FOLDER).parent / "moves_log.txt")
    PROCESSED_LOG = Path(args.processed_log) if args.processed_log else (Path(WATCH_FOLDER).parent / "processed_log.txt")
    SERVER_URL = args.server_url
    API_KEY = args.api_key
    MODEL = args.model
    MAX_CONCURRENT = max(1, args.max_concurrent)
    API_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT)

    masked_api_key = API_KEY
    if API_KEY:
        if len(API_KEY) <= 8:
            masked_api_key = "*" * len(API_KEY)
        else:
            masked_api_key = f"{API_KEY[:4]}...{API_KEY[-4:]}"

    effective_args = {
        "watch_folder": WATCH_FOLDER,
        "output_folder": OUTPUT_FOLDER,
        "log_file": str(LOG_FILE),
        "processed_log": str(PROCESSED_LOG),
        "server_url": SERVER_URL,
        "api_key": masked_api_key,
        "model": MODEL,
        "max_concurrent": MAX_CONCURRENT,
    }
    logger.info("Effective arguments in use:")
    for key, value in effective_args.items():
        logger.info(f"  {key} = {value}")

    Path(OUTPUT_FOLDER).mkdir(parents=True, exist_ok=True)
    Path(WATCH_FOLDER).mkdir(parents=True, exist_ok=True)

    if not LOG_FILE.exists():
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("UTC mtime | Old → New\n" + "-"*80 + "\n")

    client = AsyncOpenAI(base_url=SERVER_URL, api_key=API_KEY, timeout=REQUEST_TIMEOUT)

    # Create the event loop **before** starting watchdog
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start watchdog (its threads will now see the loop via global)
    observer = Observer()
    #observer = PollingObserver(timeout=2.0)  # poll every 2 second
    observer.schedule(ImageHandler(), str(WATCH_FOLDER), recursive=False)
    observer.start()

    logger.info(f"Watching: {WATCH_FOLDER}")
    logger.info(f"Moving to: {OUTPUT_FOLDER}")
    logger.info(f"Log: {LOG_FILE}")
    logger.info(f"Max concurrent: {MAX_CONCURRENT}")

    try:
        # Run the asyncio main loop (this blocks until Ctrl+C or exception)
        loop.run_until_complete(main_async(client))
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Main loop error: {e}")
    finally:
        # Cleanup
        for _ in range(MAX_CONCURRENT):  # one per worker
            loop.call_soon_threadsafe(file_queue.put_nowait, None)
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        observer.stop()
        observer.join()
        logger.info("Watcher stopped")


async def main_async(client: AsyncOpenAI):
    # Start the worker tasks
    workers = [asyncio.create_task(file_worker(client)) for _ in range(MAX_CONCURRENT)]
    #scanner = asyncio.create_task(periodic_scanner())

    try:
        # Keep running forever
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        # Cancel all workers on shutdown
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        logger.info("Workers cancelled")

if __name__ == "__main__":
    main()