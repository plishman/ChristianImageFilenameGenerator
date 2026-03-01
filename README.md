# Christian Image Filename Generator

These python scripts make API calls to Vision-supported AI Models on Openrouter etc to obtain content-appropriate filenames for locally-stored images.

## Batch processing of large numbers of image filenames

The prompt embedded in the scripts gets the AI Model to classify images taken from the folder specified with <code>--folder</code> and return a content-appropriate filename

A batch file is produced which contains file rename commands for every image file processed.

Supports resuming if interrupted.

* ConcurrentRemoteChristianImageFilenameGenerator.py

  (multithreaded - supports many API calls at once, to process large numbers of files quickly)

* RemoteChristianImageFilenameGenerator.py

  (single-threaded early version of the concurrent version, processes images one at a time)

### Usage help (ConcurrentRemoteChristianImageFilenameGenerator.py)
<pre>
usage: ConcurrentRemoteChristianImageFilenameGenerator.py [-h] [--server-url SERVER_URL] [--api-key API_KEY]
                                                          [--model MODEL] [--folder FOLDER]
                                                          [--batch-file-name BATCH_FILE_NAME]
                                                          [--processed-images-log-name PROCESSED_IMAGES_LOG_NAME]  
                                                          [--max-concurrent MAX_CONCURRENT] [--reset]

Analyze images in a folder with an OpenAI-compatible vision model, generate suggested Christian-themed filenames,  
and write rename commands to a batch file while tracking processed images.

options:
  -h, --help            show this help message and exit
  --server-url SERVER_URL
                        OpenAI-compatible API base URL (e.g., https://openrouter.ai/api/v1). (default:
                        https://openrouter.ai/api/v1)
  --api-key API_KEY     API key used to authenticate requests to the model provider. (default: <please specify     
                        your api key in command args>)
  --model MODEL         Model identifier used for image-to-filename generation. (default: x-ai/grok-4.1-fast)      
  --folder FOLDER       Root folder to scan recursively for supported image files. (default: ./images)
  --batch-file-name BATCH_FILE_NAME
                        Output batch filename that receives generated rename commands. (default:
                        rename_images.bat)
  --processed-images-log-name PROCESSED_IMAGES_LOG_NAME, --processed-log-name PROCESSED_IMAGES_LOG_NAME
                        Log filename that stores absolute paths already processed. (default:
                        processed_images.log)
  --max-concurrent MAX_CONCURRENT
                        Maximum number of concurrent image/model processing tasks. (default: 72)
  --reset               Delete processed log before running and process all images from scratch. (default: False)
</pre>

## Duplicate filename resolution with postprocess_duplicates.py

Post-processing python script to append consecutive numbers to duplicate filenames within the rename batch file output by <code>ConcurrentRemoteChristianImageFilenameGenerator.py</code>, to make them unique.

* postprocess_duplicates.py
  
<b>Running <code>postprocess_duplicates.py</code> after <code>ConcurrentRemoteChristianImageFilenameGenerator.py</code> is a necessary step when a large number of images with similar content have been processed.</b>

To rename the images, run the batch file it outputs (eg. <code>rename_images_final.bat</code>) rather than that produced by ConcurrentRemoteChristianImageFilenameGenerator.py (eg. <code>rename_images.bat</code>)

### Usage help (postprocess_duplicates.py)
<pre>
usage: postprocess_duplicates.py [-h] [--folder FOLDER] [--batch-input BATCH_INPUT] [--batch-output BATCH_OUTPUT]

Post-process rename batch commands to prevent filename collisions by adding numbered suffixes in execution order.  

options:
  -h, --help            show this help message and exit
  --folder FOLDER       Folder that contains the images and the input/output batch files. (default: ./images)      
  --batch-input BATCH_INPUT
                        Input batch filename to read rename commands from. (default: rename_images.bat)
  --batch-output BATCH_OUTPUT
                        Output batch filename to write duplicate-safe rename commands to. (default:
                        rename_images_final.bat)
</pre>

:memo: **Note:** batch-input and batch-output are expected to be different files.

## Folder Watcher

This script watches a folder <code>--watch-folder</code> and uses a vision AI Model to generate descriptive filenames for any images that are saved to or dropped into the folder.

Right-click save images from the browser (or copy from elsewhere on local storage) into the folder and they will be processed, renamed and moved to the output folder <code>--output-folder</code>.

* ChristianImageRenamerFolderWatcher.py

### Usage help (ChristianImageRenamerFolderWatcher.py)
<pre>
usage: ChristianImageRenamerFolderWatcher.py [-h] [--watch-folder WATCH_FOLDER] [--output-folder OUTPUT_FOLDER]
                                             [--log-file LOG_FILE] [--processed-log PROCESSED_LOG]
                                             [--server-url SERVER_URL] [--api-key API_KEY] [--model MODEL]
                                             [--max-concurrent MAX_CONCURRENT]

Watch a folder and rename Christian images using an LLM.

options:
  -h, --help            show this help message and exit
  --watch-folder WATCH_FOLDER
                        Input/watch folder path
  --output-folder OUTPUT_FOLDER
                        Output folder path
  --log-file LOG_FILE   Moves log file path
  --processed-log PROCESSED_LOG
                        Processed/fingerprint log file path
  --server-url SERVER_URL
                        OpenAI-compatible server base URL
  --api-key API_KEY     API key
  --model MODEL         Model name
  --max-concurrent MAX_CONCURRENT
                        Maximum concurrent worker/API operations
</pre>

:memo: **Note:** --watch-folder and --output-folder are expected to be different

<hr/>

# Image Archives

## Archive of around 27,000 Christian images with filenames generated using AI
<b>Christian Cultural and Devotional Images Archive, mostly from X. AI generated names (4.62GB ZIP)</b>
https://drive.google.com/file/d/1Ge8A6HemhHtfEpm89Mlc4YSPtS1zv14E/view?usp=sharing

## An Image archive I made over several years without the tools (named by hand)
<b>Christian Cultural and Devotional Images Archive, mostly from X. Human generated names (1.39GB ZIP)</b>
https://drive.google.com/file/d/1MOc6cB4uxx11AjGl1PttPBeT9u94xG6_/view?usp=sharing

Image Copyrights: Various, acknowledged (Fair use/Devotional use only)
