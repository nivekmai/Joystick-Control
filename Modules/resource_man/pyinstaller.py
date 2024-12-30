import os
import types
import contextlib

try:
    from importlib.machinery import SOURCE_SUFFIXES
except (ImportError, Exception):
    SOURCE_SUFFIXES = ['.py', '.pyw', '.py2', '.py3']

from resource_man.__meta__ import version as __version__
from resource_man.importlib_interface import \
    READ_API, FILES_API, Traversable, contents, is_resource, read_binary, read_text, files, as_file
from resource_man.interface import \
    ResourceNotAvailable, Resource, ResourceManagerInterface, ResourceManager, \
    get_global_manager, set_global_manager, temp_manager, add_manager, remove_manager, clear, \
    register_resource, register, register_data, register_directory, unregister, has_resource, \
    get_resources, get_resource, get_binary, get_text, registered_datas, \
    MISSING


__all__ = [
    'find_datas', 'EXCLUDE_EXT', 'SOURCE_SUFFIXES',

    'READ_API', 'FILES_API', 'Traversable', 'contents', 'is_resource', 'read_binary', 'read_text', 'files', 'as_file',

    'ResourceNotAvailable', 'Resource', 'ResourceManagerInterface', 'ResourceManager',
    'get_global_manager', 'set_global_manager', 'temp_manager', 'add_manager', 'remove_manager',
    'clear', 'register_resource', 'register', 'register_data', 'register_directory', 'unregister',
    'has_resource', 'get_resources', 'get_resource', 'get_binary', 'get_text', 'registered_datas',
    'MISSING',
    '__version__'
    ]


EXCLUDE_EXT = SOURCE_SUFFIXES + ['.pyc', '.pyd']


def find_datas(package, exclude_ext=None, use_dest_dirs=True, **kwargs):
    """Collect data files for pyinstaller.

    Args:
        package (types.ModuleType/str/Traversable): Top level package module or module name.
        exclude_ext (list)[None]: List of extensions to not include in the pyinstaller data.
        use_dest_dirs (bool)[True]: If True the destination will be a directory. If False the dest will be the filename.

    Returns:
        datas (list): List of (abs file path, rel install path). This will also include subdirectories.
    """
    if exclude_ext is None:
        exclude_ext = EXCLUDE_EXT

    datas = []
    pkg_name = package
    if isinstance(package, types.ModuleType):
        pkg_name = package.__package__

    with contextlib.suppress(ImportError, Exception):
        toplvl = files(package)
        with as_file(toplvl) as n:
            toplvl_filename = str(n)  # n should be a Path object, but I noticed it was a str anyway
        subdirs = [toplvl]
        while True:
            try:
                directory = subdirs.pop(0)
            except IndexError:
                break

            for path in directory.iterdir():
                if path.name == '__pycache__':
                    continue

                if path.is_dir():
                    # Add subpackage
                    subdirs.append(path)
                elif path.suffix not in exclude_ext:
                    # Assume this is a resource.
                    with as_file(path) as filename:
                        try:
                            filename = str(filename.resolve())
                        except (AttributeError, Exception):
                            pass

                        relpath = os.path.join(pkg_name, os.path.relpath(filename, toplvl_filename))
                        if use_dest_dirs:
                            relpath = os.path.dirname(relpath)

                        data = (filename, relpath)
                        if data not in datas:
                            datas.append(data)

    return datas
