# Remote Worker

## Separation of Responsibilities

There are several reasons to move some processing out of the main code base for security or performance:

- If there is a security exploit in the image processing library, it will only impact this remote worker
- If you need to send some network requests (e.g., link previewing) to a third party, running those tasks on separate servers to prevent leaking the IP addresses of the main web instances
- If some processing does not rely on the other part of the main code base, then you can move them into the remote worker for better performance

## Python Version

This project should always be using the latest version of Python. At the time of this writing, it is 3.10.0. You can install it via [pyenv](https://github.com/pyenv/pyenv).

## Ubuntu Packages

These packages need required for manipulating images:

```
sudo apt install libimage-exiftool-perl jhead libmagic-dev
```

When developing on macOS, you can install those packages with Homebrew:

```
brew install exiftool jhead
```
