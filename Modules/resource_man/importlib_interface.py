import os
import sys
import contextlib
import inspect
from pathlib import Path

files = None
as_file = None
read_text = None
read_binary = None
contents = None
is_resource = None
Traversable = Path

READ_API = 'resource_man'
FILES_API = 'resource_man'

# Try reading imports
try:
    from importlib.resources import contents, is_resource, read_binary, read_text
    from importlib.abc import Traversable
    READ_API = 'importlib.resources'
except (ImportError, Exception):
    pass  # DO NOT USE importlib_resources! It does not work with PyInstaller. Throws Can't open orphan path error!
    # try:
    #     from importlib_resources import contents, is_resource, read_binary, read_text
    #     from importlib_resources.abc import Traversable
    #     READ_API = 'importlib_resources'
    # except (ImportError, Exception):
    #     pass

# Try files imports
try:
    from importlib.resources import files, as_file
    FILES_API = 'importlib.resources'
except (ImportError, Exception):
    pass  # DO NOT USE importlib_resources! It does not work with PyInstaller. Throws Can't open orphan path error!
    # try:
    #     from importlib_resources import files, as_file
    #     FILES_API = 'importlib_resources'
    # except (ImportError, Exception):
    #     pass


__all__ = [
    'READ_API', 'FILES_API', 'EXE_PATH',
    'Traversable', 'contents', 'is_resource', 'read_binary', 'read_text', 'files', 'as_file',
    'rsc_files', 'rsc_as_file', 'rsc_read_binary', 'rsc_read_text', 'rsc_contents', 'rsc_is_resource'
    ]


EXE_PATH = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))

if not hasattr(Traversable, 'read_bytes'):
    def path_read_bytes(self):
        with open(str(self), 'rb') as f:
            return f.read()

    Traversable.read_bytes = path_read_bytes

if not hasattr(Traversable, 'read_text'):
    def path_read_text(self, encoding='utf-8', errors='strict'):
        with open(str(self), 'r', encoding=encoding, errors=errors) as f:
            return f.read()

    Traversable.read_text = path_read_text


def rsc_files(module):
    if isinstance(module, str):
        # Check for the executable path
        if getattr(sys, 'frozen', False):
            path = Path(EXE_PATH) / module.replace('.', '/')
            if path.with_suffix('').name == '__init__':
                path = path.parent
            if path.exists():
                return path

        # Find the module path from the imported module
        if '.' in module:
            # Import the top level package and manually add a directory for each "."
            toplvl, remain = module.split('.', 1)
        else:
            toplvl, remain = module, ''

        # Get or import the module
        try:
            module = sys.modules[toplvl]
            path = Path(inspect.getfile(module))
        except (KeyError, Exception):
            try:
                module = __import__(toplvl)
                path = Path(inspect.getfile(module))
            except (ImportError, Exception):
                module = toplvl
                path = Path(module)

        # Get the path of the module
        if path.with_suffix('').name == '__init__':
            path = path.parent

        # Find the path from the top level module
        for pkg in remain.split('.'):
            path = path.joinpath(pkg)
    else:
        path = Path(inspect.getfile(module))
    if path.with_suffix('').name == '__init__':
        path = path.parent
    return path


@contextlib.contextmanager
def rsc_as_file(path):
    p = path

    # Find this path from the executable
    if (isinstance(p, str) and not os.path.exists(p)) or (isinstance(p, (Path, Traversable)) and not p.exists()):
        p = os.path.join(EXE_PATH, str(path))
    if (isinstance(p, str) and not os.path.exists(p)) or (isinstance(p, (Path, Traversable)) and not p.exists()):
        p = os.path.join(EXE_PATH, '', str(path))

    yield Path(p)  # Documentation says should be Path object, but I noticed it was a string.


def rsc_read_binary(package, resource):
    """Return the binary contents of the resource."""
    return files(package).joinpath(resource).read_bytes()


def rsc_read_text(package, resource, encoding='utf-8', errors='strict'):
    """Return the decoded string of the resource.

    The decoding-related arguments have the same semantics as those of
    bytes.decode().
    """
    return files(package).joinpath(resource).read_text(encoding, errors)


def rsc_contents(package):
    """Return an iterable of entries in 'package'.

    Note that not all entries are resources.  Specifically, directories are
    not considered resources.  Use `is_resource()` on each entry returned here
    to check if it is a resource or not.
    """
    return iter([p.name for p in files(package).iterdir()])


def rsc_is_resource(package, name):
    """True if 'name' is a resource inside 'package'.

    Directories are *not* resources.
    """
    pkg = files(package)
    path = pkg.joinpath(name)
    if path.exists() and not path.is_dir():
        return True

    try:
        package_contents = set(contents(package))
    except (NotADirectoryError, FileNotFoundError):
        return False
    if name not in package_contents:
        return False
    # Just because the given file_name lives as an entry in the package's
    # contents doesn't necessarily mean it's a resource.  Directories are not
    # resources, so let's try to find out if it's a directory or not.
    path = Path(pkg.__spec__.origin).parent / name
    return path.is_file()


if read_text is None:
    read_text = rsc_read_text
    read_binary = rsc_read_binary
    contents = rsc_contents
    is_resource = rsc_is_resource
    Traversable = Path

if files is None:
    files = rsc_files
    as_file = rsc_as_file
