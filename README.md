[![PyPI Version](https://img.shields.io/pypi/v/gigafile.svg)](https://pypi.python.org/pypi/gigafile)

# gfile

A python CLI/module to download and upload from [gigafile](https://gigafile.jp/). (The original domain `gigafile.nu` is currently down.)

Note: PyPI package name is `gigafile` since `gfile` wasn't available. Both CLI and module names are still `gfile`.

A major update from [the original](https://github.com/Sraq-Zit/gfile). Highlights:

* Fixed multi-thread uploading (and made sure each threads finish in order so the final file is not broken)
* Fixed download filename issue
* Some refactoring and QoL changes.

## Install
    $ pip install -U gigafile
or

    $ pip install -U git+https://github.com/fireattack/gfile.git

## Usage
### CLI
```bash
$ gfile upload path/to/file

$ gfile download https://66.gigafile.jp/0320-b36ec21d4a56b143537e12df7388a5367

$ gfile -h
usage: Gfile [-h] [--version] [-p] [-o OUTPUT] [--aria2 [ARIA2]] [-n THREAD_NUM] [-s CHUNK_SIZE] [-m CHUNK_COPY_SIZE] [-t TIMEOUT] [-k KEY]
             [--mute] [--verify | --no-verify]
             {download,upload} file_or_url

positional arguments:
  {download,upload}     upload or download
  file_or_url           filename to upload or url to download

options:
  -h, --help            show this help message and exit
  --version             show version and exit
  -p, --hide-progress   hide progress bar
  -o OUTPUT, --output OUTPUT
                        output filename for download (default: use original name)
  --aria2 [ARIA2]       download with aria2. You can also specify optional arguments (default: "-x10 -s10", make sure to quote). `-o` is already
                        automatically included.
  -n THREAD_NUM, --thread-num THREAD_NUM
                        number of threads used for upload [default: 8]
  -s CHUNK_SIZE, --chunk-size CHUNK_SIZE
                        chunk size per upload in bytes; note: chunk_size*thread will be loaded into memory [default: 100MB]
  -m CHUNK_COPY_SIZE, --copy-size CHUNK_COPY_SIZE
                        specifies size to copy the main file into pieces [default: 1MB]
  -t TIMEOUT, --timeout TIMEOUT
                        specifies timeout time (in seconds) [default: 10]
  -k KEY, --key KEY, --password KEY
                        specifies the key/password for the file
  --mute                mute initial message and warnings (only the final result and errors will be shown)
  --verify              enable verification (default)
  --no-verify           disable verification
```

### Module
#### Import
```py
from gfile import GFile
```
#### Download
```py
filename = GFile('https://XX.gigafile.jp/YYY').download()
```

#### Upload
```py
url = GFile('path/to/file', progress=True).upload().get_download_page()
```