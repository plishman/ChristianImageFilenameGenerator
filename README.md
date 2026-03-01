# Christian Image Filename Generator

These python scripts make API calls to Vision-supported AI Models on Openrouter etc.

The prompt embedded in the scripts gets the AI Model to classify images taken from the folder specified with --folder and return a content-appropriate filename

A batch file is produced which contains file rename commands for every image file processed.

Supports resuming if interrupted.

* ConcurrentRemoteChristianImageFilenameGenerator.py

  (multithreaded - supports many API calls at once, to process large numbers of files quickly)

* RemoteChristianImageFilenameGenerator.py

  (single-threaded early version of the concurrent version, processes images one at a time)

## Usage help (ConcurrentRemoteChristianImageFilenameGenerator.py)
Scan images in a folder, ask an OpenAI-compatible vision model for filename suggestions, write rename commands to a batch file, and track already-processed images for resumable runs.

| options ||
|----------|-|
| -h, --help | show this help message and exit |
|--server-url SERVER_URL | OpenAI-compatible API base URL. (default: https://openrouter.ai/api/v1) |
| --api-key API_KEY     | API key used to authenticate model requests. (default: <please specify your api key in command args>) |
| --model MODEL         | Model identifier for image-to-filename generation. (default: x-ai/grok-4.1-fast) |
| --folder FOLDER       | Root folder to scan recursively for supported image files. (default: ./images) |
| --batch-file-name BATCH_FILE_NAME | Output batch filename that receives generated rename commands. (default: rename_images.bat) |
| --processed-images-log-name PROCESSED_IMAGES_LOG_NAME | Log filename storing absolute paths already processed. (default: processed_images.log) |
| --reset | Delete processed log before running and process all images from scratch. (default: False) |

Christian Cultural and Devotional Images Archive, mostly from X. AI generated names (4.62GB ZIP)
https://drive.google.com/file/d/1Ge8A6HemhHtfEpm89Mlc4YSPtS1zv14E/view?usp=sharing

Christian Cultural and Devotional Images Archive, mostly from X. Human generated names (1.39GB ZIP)
https://drive.google.com/file/d/1MOc6cB4uxx11AjGl1PttPBeT9u94xG6_/view?usp=sharing

Copyright: Various, acknowledged (Fair use/Devotional use only)

