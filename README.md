# Remote Worker

## Separation of Responsibilities

There are several reasons to move some processing out of the main code base for security or performance:

- If there is a security exploit in the image processing library, it will only impact this remote worker
- If you need to send some network requests (e.g., link previewing) to a third party, running those tasks on separate servers to prevent leaking the IP addresses of the main web instances
- If some processing does not rely on the other part of the main code base, then you can move them into the remote worker for better performance

## Python Version

This project should always be using the latest version of Python. At the time of this writing, it is 3.10.0. You can install it via [pyenv](https://github.com/pyenv/pyenv).

We included a [pre-commit](https://pre-commit.com/) [config](./.pre-commit-config.yaml) to ensure code quality and consistency.

## Ubuntu Packages

These packages are required for manipulating images:

```
sudo apt install libimage-exiftool-perl jhead libmagic-dev
```

When developing on macOS, you can install those packages with Homebrew:

```
brew install exiftool jhead libmagic
```

## Endpoints

### images/prepare_jpeg

Accepts a multipart/form-data request with the following parameters:

    - file: the image to process

Two processes are performed on the image:

- Remove GPS info from EXIF metadata
- Adjust the orientation of the image to make it work in browsers that don't support EXIF orientation

### images/fit/:box

Accepts a multipart/form-data request with the following parameters:

    - file: the image to process

Returns a new image that fits within the given box, and the image's aspect ratio is preserved.

### images/rescale_avatar

Accepts a multipart/form-data request with the following parameters:

    - file: the image to process
    
Return a JSON object with the processed versions of the image:

    - avatar24: a 24x24 version of the image
    - avatar48: a 48x48 version of the image
    - avatar73: a 73x73 version of the image
    - avatar128: a 128x128 version of the image if the original image is larger than 128x128
    - avatar256: a 256x256 version of the image if the original image is larger than 256x256
    - avatar512: a 512x512 version of the image if the original image is larger than 512x512

These original image formats are supported:

- JPEG
- JPEG 2000 (JP2)
- PNG
- GIF
- BMP
- TIFF
- WEBP
- HEIF
- AVIF
- PSD
- ICNS

The output format is always in PNG.

curl example for sending such a request:

    curl -X POST -F "file=@/path/to/image.jpg" http://localhost:5000/images/rescale_avatar
