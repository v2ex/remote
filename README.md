# Various Micro Services

## Separation of Responsibilities

You may want to move some processing out of the main monolith code base for security or performance reasons, like network test or image processing, since they do not depend on the main codebase.

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
