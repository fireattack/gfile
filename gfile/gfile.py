import concurrent.futures
import functools
import io
import math
import re
import time
import uuid
from datetime import datetime
from os import rename
from pathlib import Path
from subprocess import run

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from requests_toolbelt import MultipartEncoder, StreamingIterator
from tqdm import tqdm
from urllib3.util.retry import Retry


def bytes_to_size_str(bytes):
   if bytes == 0:
       return "0B"
   units = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
   i = int(math.floor(math.log(bytes, 1024)))
   p = math.pow(1024, i)
   return f"{bytes/p:.02f} {units[i]}"


def size_str_to_bytes(size_str):
    if isinstance(size_str, int):
        return size_str
    m = re.search(r'^(?P<num>\d+) ?((?P<unit>[KMGTPEZY]?)(iB|B)?)$', size_str, re.IGNORECASE)
    assert m
    units = ("B", "K", "M", "G", "T", "P", "E", "Z", "Y")
    unit = (m['unit'] or 'B').upper()
    return int(math.pow(1024, units.index(unit)) * int(m['num']))


def requests_retry_session(
    retries=5,
    backoff_factor=0.2,
    status_forcelist=None, # (500, 502, 504)
    session=None,
):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def split_file(input_file, out, target_size=None, start=0, chunk_copy_size=1024*1024):
    input_file = Path(input_file)
    size = 0

    input_size = input_file.stat().st_size
    if target_size is None:
        output_size = input_size - start
    else:
        output_size = min(target_size, input_size - start)

    with open(input_file, 'rb') as f:
        f.seek(start)
        while True:
            if size == output_size: break
            if size > output_size:
                raise Exception(f'Size ({size}) is larger than {target_size} bytes!')
            current_chunk_size = min(chunk_copy_size, output_size - size)
            chunk = f.read(current_chunk_size)
            if not chunk: break
            size += len(chunk)
            out.write(chunk)


class GFile:
    def __init__(self, file_or_url, progress=False, thread_num=4, chunk_size=1024*1024*10, chunk_copy_size=1024*1024, timeout=10,
                 aria2=False, key=None, mute=False, verify=True, **kwargs) -> None:
        self.file_or_url = file_or_url
        self.chunk_size = size_str_to_bytes(chunk_size)
        self.chunk_copy_size = size_str_to_bytes(chunk_copy_size)
        self.thread_num=thread_num
        self.progress = progress
        self.data = None
        self.pbar = None
        self.timeout = timeout
        self.session = requests_retry_session()
        self.session.request = functools.partial(self.session.request, timeout=self.timeout)
        self.cookies = None
        self.current_chunk = 0
        self.aria2 = aria2
        self.mute = mute
        self.verify = verify
        self.key = key


    def upload_chunk(self, chunk_no, chunks):
        bar = self.pbar[chunk_no % self.thread_num] if self.pbar else None
        with io.BytesIO() as f:
            split_file(self.file_or_url, f, self.chunk_size, start=chunk_no * self.chunk_size, chunk_copy_size=self.chunk_copy_size)
            chunk_size = f.tell()
            f.seek(0)
            fields = {
                "id": self.token,
                "name": Path(self.file_or_url).name,
                "chunk": str(chunk_no),
                "chunks": str(chunks),
                "lifetime": "100",
                "file": ("blob", f, "application/octet-stream"),
            }
            form_data = MultipartEncoder(fields)
            headers = {
                "content-type": form_data.content_type,
            }
            # convert the form-data into a binary string, this way we can control/throttle its read() behavior
            form_data_binary = form_data.to_string()
            del form_data

        size = len(form_data_binary)
        if bar:
            bar.desc = f'chunk {chunk_no + 1}/{chunks}'
            bar.reset(total=size)
            # bar.refresh()

        def gen():
            offset = 0
            while True:
                if offset < size:
                    update_tick = 1024 * 128
                    yield form_data_binary[offset:offset + update_tick]
                    if bar:
                        bar.update(min(update_tick, size - offset))
                        bar.refresh()
                    offset += update_tick
                else:
                    if chunk_no != self.current_chunk:
                        time.sleep(0.01)
                    else:
                        break
        while True:
            try:
                streamer = StreamingIterator(size, gen())
                resp = self.session.post(f"https://{self.server}/upload_chunk.php", data=streamer, headers=headers)
            except Exception as ex:
                if not self.mute:
                    print(ex)
                    print('Retrying...')
            else:
                break

        resp_data = resp.json()
        self.current_chunk += 1

        if 'url' in resp_data:
            self.data = resp_data
        if 'status' not in resp_data or resp_data['status']:
            print(resp_data)
            self.failed = True


    def upload(self):
        self.token = uuid.uuid1().hex
        self.pbar = None
        self.failed = False
        assert Path(self.file_or_url).exists()
        size = Path(self.file_or_url).stat().st_size
        chunks = math.ceil(size / self.chunk_size)
        if not self.mute:
            print(f'Filesize {bytes_to_size_str(size)}, chunk size: {bytes_to_size_str(self.chunk_size)}, total chunks: {chunks}')

        if self.progress:
            self.pbar = []
            for i in range(self.thread_num):
                self.pbar.append(tqdm(total=size, unit="B", unit_scale=True, leave=False, unit_divisor=1024, ncols=100, position=i))

        self.server = re.search(r'var server = "(.+?)"', self.session.get('https://gigafile.nu/').text)[1]

        # upload the first chunk to set cookies properly.
        self.upload_chunk(0, chunks)

        # upload second to second last chunk(s)
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread_num) as ex:
            futures = {ex.submit(self.upload_chunk, i, chunks): i for i in range(1, chunks)}
            try:
                for future in concurrent.futures.as_completed(futures):
                    if self.failed:
                        print('ERROR: Upload failed!')
                        for future in futures:
                            future.cancel()
                        return self
            except KeyboardInterrupt:
                print('\nUser cancelled the operation.')
                for future in futures:
                    future.cancel()
                return self

        if self.pbar:
            for bar in self.pbar:
                bar.close()
        print('')
        if 'url' not in self.data:
            print('ERROR: Something went wrong and upload failed. Returned data:', self.data)
            return self
        self.data['finished_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return self # for chain


    def get_download_page(self):
        uploaded_url = self.data['url']

        f = Path(self.file_or_url)
        f_size = f.stat().st_size
        if self.verify:
            if not self.mute:
                print(f"Check if the file {f.name} is uploaded successfully...")
            files_info = self.parse_download_page(uploaded_url)
            file_id = files_info[0][2]
            download_url = uploaded_url.rsplit('/', 1)[0] + '/download.php?file=' + file_id
            with self.session.get(download_url, stream=True) as r:
                uploaded_size = int(r.headers.get('Content-Length', 0))
            if not uploaded_size or uploaded_size != f_size:
                print(f"ERROR: File size of {f.name} at {uploaded_url} mismatches: expected {f_size}, got {uploaded_size}.")
                print('This means the upload is corrupted. Please try again.')
                return
            if not self.mute:
                print(f"Uploaded file {f.name} is verified successfully.")

        print(f"Finished at {self.data['finished_at']}, filename: {f.name}, size: {bytes_to_size_str(f_size)}")
        print(uploaded_url)
        return uploaded_url


    def _fetch_real_filename(self, server_id, file_id, fallback_name):
        """Fetch the real filename when it's masked in the HTML."""
        try:
            timestamp = int(time.time() * 1000) # not really required, but just to be safe
            api_url = f'https://{server_id}x.gigafile.nu/get_uploaded_file_name_jx.php?file={file_id}&_={timestamp}'
            r = self.session.get(api_url)
            r.raise_for_status()
            data = r.json()
            if 'filename' in data and data['filename']:
                return data['filename']
        except Exception as ex:
            if not self.mute:
                print(f'Warning: Failed to fetch real filename for {file_id}. Using fallback name. Error: {ex}')
        return fallback_name


    def parse_download_page(self, url):
        m = re.search(r'^https?:\/\/(\d+?)\.gigafile\.nu\/([a-z0-9-]+)$', url)
        if not m:
            print(f'ERROR: Invalid URL: {url}. It should be a valid gigafile URL.')
            return
        server_id = m[1]
        file_id = m[2]
        r = self.session.get(url) # setup cookie
        files_info = []
        try:
            soup = BeautifulSoup(r.text, 'html.parser')
            if soup.select_one('#contents_matomete'):
                print('Matomete page (multiple files). Files will be downloaded one by one.')
                for ele in soup.select('.matomete_file'):
                    web_name = ele.select_one('.matomete_file_info > span:nth-child(2)').text.strip()
                    file_id = re.search(r'download\(\d+, *\'(.+?)\'', ele.select_one('.download_panel_btn_dl')['onclick'])[1]
                    size_str = re.search(r'（(.+?)）', ele.select_one('.matomete_file_info > span:nth-child(3)').text.strip())[1]
                    if '*' in web_name:
                        web_name = self._fetch_real_filename(server_id, file_id, web_name)
                    files_info.append((web_name, size_str, file_id))
            else:
                size_str = soup.select_one('.dl_size').text.strip()
                web_name = soup.select_one('#dl').text.strip()
                if '*' in web_name:
                    web_name = self._fetch_real_filename(server_id, file_id, web_name)
                files_info.append((web_name, size_str, file_id))
        except Exception as ex:
            print(f'ERROR: Failed to parse the page {url}.')
            print(ex)
            print('Please report it back to the developer.')
            return
        if len(files_info) > 1:
            print(f'Found {len(files_info)} files in the page.')
        return files_info


    def download(self, output=None):
        downloaded = []
        files_info = self.parse_download_page(self.file_or_url)
        if not files_info:
            return downloaded
        for idx, (web_name, size_str, file_id) in enumerate(files_info, 1):
            print(f'Name: {web_name}, size: {size_str}, id: {file_id}')
            # only sanitize web filename. User provided output string(s) are on their own.
            if not output:
                filename = re.sub(r'[\\/:*?"<>|]', '_', web_name)
            else:
                if len(files_info) > 1:
                    # if there are more than one files, append idx to the filename
                    filename = output + f'_{idx}'
                else:
                    filename = output

            download_url = self.file_or_url.rsplit('/', 1)[0] + '/download.php?file=' + file_id
            if self.key:
                download_url += f'&dlkey={self.key}'
            if self.aria2:
                cookie_str = "; ".join([f"{cookie.name}={cookie.value}" for cookie in self.session.cookies])
                cmd = ['aria2c', download_url, '--header', f'Cookie: {cookie_str}', '-o', filename]
                cmd.extend(self.aria2.split(' '))
                run(cmd)
                continue

            temp = filename + '.dl'
            with self.session.get(download_url, stream=True) as r:
                r.raise_for_status()
                filesize = int(r.headers['Content-Length'])
                if self.progress:
                    desc = filename if len(filename) <= 20 else filename[0:11] + '..' + filename[-7:]
                    self.pbar = tqdm(total=filesize, unit='B', unit_scale=True, unit_divisor=1024, desc=desc)
                with open(temp, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=self.chunk_copy_size):
                        f.write(chunk)
                        if self.pbar: self.pbar.update(len(chunk))
            if self.pbar: self.pbar.close()

            filesize_downloaded = Path(temp).stat().st_size
            print(f'Filesize check: expected: {filesize}; actual: {filesize_downloaded}', end=' ')
            if filesize == filesize_downloaded:
                print("Succeeded.")
                rename(temp, filename)
            else:
                print(f"ERROR: Downloaded file is corrupt. Please check the broken file at {temp} and delete it yourself if needed.")
            downloaded.append(filename)
        return downloaded
