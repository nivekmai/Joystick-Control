import os
import sys
import copy
import atexit
import contextlib
from .importlib_interface import EXE_PATH, contents, is_resource, read_binary, read_text, files, as_file
from pathlib import Path


try:
    from dataclasses import MISSING
except (ImportError, Exception):
    MISSING = object()


__all__ = [
    'ResourceNotAvailable', 'Resource', 'ResourceManagerInterface', 'ResourceManager',
    'get_global_manager', 'set_global_manager', 'temp_manager', 'add_manager', 'remove_manager',
    'clear', 'register_resource', 'register', 'register_data', 'register_directory', 'unregister',
    'has_resource', 'get_resources', 'get_resource', 'get_binary', 'get_text', 'registered_datas',
    'MISSING'
    ]


class ResourceNotAvailable(Exception):
    pass


class Resource:
    def __init__(self, package, name, alias=MISSING, manager=None, data=None, **kwargs):
        """Initialize the resource object.

        Args:
            package (str): Package or module name where the resource can be found (EX: "mylib.mysubpkg")
            name (str): Name of the resource (EX: "myimg.png").
            alias (str)[MISSING]: Shortcut alias name identifer for the resource.
                ... (Ellipsis) will be the name with the extension (EX: "myimg.png")
                None will be the name without the extension (EX: "myimg")
            manager (ResourceManager)[None]: Manager that holds this object.
            data (bytes/object)[None]: Stored or read in data.
            **kwargs (dict): Dictionary of keyword arguments to set as resource attributes.
        """
        self.manager = manager
        self.raw_alias = alias
        self.package = package
        self.name = name
        self.data = data
        self._context = None
        self._context_obj = None

        # Set all keyword arguments as attributes
        for k, v in kwargs.items():
            try:
                setattr(self, k, v)
            except (AttributeError, TypeError, ValueError, Exception):
                pass

    @property
    def package_path(self):
        """Return the package path."""
        pkg = self.package.replace('.', '/')
        name = self.name
        if pkg and name:
            return '/'.join((pkg, self.name))
        elif pkg:
            return pkg
        else:
            return name

    @property
    def alias(self):
        """Return the alias name identifier."""
        if self.raw_alias is MISSING:
            return self.package_path
        elif self.raw_alias is ...:
            return self.name
        elif self.raw_alias is None:
            return os.path.splitext(self.name)[0]
        return self.raw_alias

    @alias.setter
    def alias(self, value):
        self.raw_alias = value

    # Backwards compatibility support
    identifier = alias

    def is_resource(self):
        """Return if this resource is file based.

        This is mainly used for collecting data files. Resource's that were given data with fake packages and
        names will return False.
        """
        try:
            return is_resource(self.package, self.name)
        except (AttributeError, TypeError, ValueError, Exception):
            try:
                f = self.files()
                return f.exists() and not f.is_dir()
            except (AttributeError, TypeError, ValueError, Exception):
                return False

    def files(self):
        try:
            return files(self.package).joinpath(self.name)
        except (AttributeError, TypeError, ValueError, Exception):
            return Path(self.package_path)

    @contextlib.contextmanager
    def as_file(self):
        f = self.files()
        try:
            with as_file(f) as file:
                yield file
        except (ValueError, TypeError, FileNotFoundError, Exception) as err:
            package_path = str(self.package_path)
            if os.path.exists(package_path):
                yield package_path
            else:
                raise err

    def contents(self):
        try:
            if '/' in self.name or '\\' in self.name:
                return [f.name for f in self.files().parent.iterdir()]
        except (ValueError, TypeError, Exception):
            pass
        try:
            return contents(self.package)
        except (ValueError, TypeError, Exception):
            return []

    def read_bytes(self):
        error = None
        if isinstance(self.data, bytes):
            return self.data
        elif isinstance(self.data, str):
            return self.data.encode('utf-8')
        elif self.data is not None:
            try:
                return bytes(self.data)
            except (AttributeError, TypeError, OSError, Exception) as err:
                error = err
                try:
                    return str(self.data).encode('utf-8')
                except (AttributeError, TypeError, OSError, Exception):
                    pass
        else:
            try:
                self.data = read_binary(self.package, self.name)
                return self.data
            except (AttributeError, TypeError, OSError, Exception) as err:
                error = err
                try:
                    self.data = self.files().read_bytes()
                    return self.data
                except (AttributeError, TypeError, OSError, Exception):
                    pass
        raise ResourceNotAvailable(str(error))

    read_binary = read_bytes

    def read_text(self, encoding='utf-8', errors='strict'):
        error = None
        if isinstance(self.data, str):
            return self.data
        elif isinstance(self.data, bytes):
            return self.data.decode(encoding, errors)
        elif self.data is not None:
            try:
                return bytes(self.data)
            except (AttributeError, TypeError, OSError, Exception) as err:
                error = err
                try:
                    return str(self.data).encode('utf-8')
                except (AttributeError, TypeError, OSError, Exception):
                    pass
        else:
            try:
                self.data = read_text(self.package, self.name, encoding, errors)
                return self.data
            except (AttributeError, TypeError, OSError, Exception) as err:
                error = err
                try:
                    self.data = self.files().read_text(encoding, errors)
                    return self.data
                except (AttributeError, TypeError, OSError, Exception):
                    pass
        raise ResourceNotAvailable(str(error))

    def _enter_context(self):
        """Use "as_file" to enter the with context block for the life of the application in order to get the filepath.
        """
        if self.data is not None and not isinstance(self.data, (bytes, str)):
            self._context_obj = self.data
        else:
            self._context = self.as_file()
            self._context_obj = self._context.__enter__()

        try:
            self._context_obj = self._context_obj.resolve()  # Get proper path capitalization
        except (AttributeError, Exception):
            pass
        atexit.register(self._exit_context)

    def _exit_context(self):
        """Exit the context object that was used with "as_file"."""
        try:
            self._context.__exit__()
        except (ResourceNotAvailable, OSError, TypeError, ValueError, Exception):
            pass
        finally:
            self._context_obj = None
            self._context = None

    def __str__(self):
        """Return the full string file path. I'm not sure if this will always work. "as_file" should be used."""
        try:
            if self._context_obj:
                return str(self._context_obj)

            # Use "as_file" to enter the context and return the filepath
            self._enter_context()
            if self._context_obj:
                return str(self._context_obj)

            # Use files to return the path. Should I even do this?
            filename = self.files()
            try:
                filename = filename.resolve()
            except (AttributeError, OSError, Exception):
                pass
            return str(filename)
        except (ResourceNotAvailable, OSError, TypeError, ValueError, Exception):
            pass

        # Return the simple package path from the working directory.
        pp = orig_pp = str(self.package_path)
        if not os.path.exists(pp):
            pp = os.path.join(EXE_PATH, pp)
            if not os.path.exists(pp):
                pp = os.path.join(EXE_PATH, '', pp)
            if not os.path.exists(pp):
                pp = orig_pp
        return pp

    def __fspath__(self):
        """Return the file path. This is not recommended. You should be using 'as_file' or 'read_text'."""
        return self.__str__()

    def __eq__(self, other):
        if isinstance(other, str):
            return other == self.alias or \
                   other.replace('\\', '/') == self.package_path
        return super().__eq__(other)

    def __repr__(self):
        kwargs = {'cls': self.__class__.__name__, 'package': self.package, 'name': self.name, 'alias': self.alias}
        return '{cls}(package={package}, name={name}, alias={alias})'.format(**kwargs)


class ResourceManagerInterface(object):
    RESOURCE_CLASS = Resource

    def __init__(self, *resources, **kwargs):
        if not hasattr(self, 'managers'):
            self.managers = []

        super(ResourceManagerInterface, self).__init__()
        self.init(*resources, **kwargs)

    def __iter__(self):
        raise NotImplementedError

    def __contains__(self, item):
        raise NotImplementedError

    def __getitem__(self, item):
        raise NotImplementedError

    def __setitem__(self, key, value):
        raise NotImplementedError

    def append(self, resource):
        if hasattr(resource, 'manager') and resource.manager is None:
            resource.manager = self
        raise NotImplementedError

    def pop(self, key, **kwargs):
        raise NotImplementedError

    def init(self, *resources, **kwargs):
        """Initialize"""
        self.managers = list(kwargs.pop('managers', getattr(self, 'managers', [])))

        # Set keyword arguments as attributes
        for k, v in kwargs.items():
            setattr(self, k, v)

        # Add resources
        for resource in resources:
            self.append(resource)

    def add_manager(self, man):
        """Add a manager to help with saving all managers."""
        if man in self.managers:
            # Remove so the manager will be at the end.
            try:
                self.managers.remove(man)
            except (AttributeError, TypeError, ValueError, Exception):
                pass
        self.managers.append(man)

    def remove_manager(self, man):
        """Remove a linked manager."""
        try:
            self.managers.remove(man)
        except (TypeError, ValueError, Exception):
            pass

    def register_resource(self, rsc, **kwargs):
        """Register a resource.

        Args:
            rsc (Resource): Resource object to register and access later.

        Returns:
            rsc (Resource): Resource object that was registered
        """
        self.append(rsc)
        return rsc

    def register(self, package, name, alias=MISSING, **kwargs):
        """Register a resource. You can optionally have an alias name identifier.
        When using the alias the last resource registered with the same alias will be used.

        Args:
            package (str): Package name ('check_lib.check_sub')
            name (str): Name of the resource ('edit-cut.png')
            alias (str)[MISSING]: Shortcut alias name identifer for the resource.
                ... (Ellipsis) will be the name with the extension (EX: "myimg.png")
                None will be the name without the extension (EX: "myimg")
            **kwargs (dict): Dictionary of keyword arguments to set as attributes to the resource.
        """
        if 'manager' not in kwargs:
            kwargs['manager'] = self
        rsc = self.RESOURCE_CLASS(package, name, alias=alias, **kwargs)
        return self.register_resource(rsc)

    def register_data(self, data, package, name, alias=MISSING, **kwargs):
        """Register a plain data resource.

        Args:
            data (bytes/str/object)[None]: Plain data to store.
            package (str)[None]: Package name ('check_lib.check_sub')
            name (str)[None]: Name of the resource ('edit-cut.png')
            alias (str)[MISSING]: Shortcut alias name identifer for the resource.
                ... (Ellipsis) will be the name with the extension (EX: "myimg.png")
                None will be the name without the extension (EX: "myimg")
            **kwargs (dict): Dictionary of keyword arguments to set as attributes to the resource.
        """
        if 'manager' not in kwargs:
            kwargs['manager'] = self
        rsc = self.RESOURCE_CLASS(package=package, name=name, alias=alias, data=data, **kwargs)
        return self.register_resource(rsc)

    def register_directory(self, package, directory='', recursive=False, extensions=None, exclude=None, **kwargs):
        """Register all items in a directory.

        Note:
            This does not register the __init__.py module.

        Args:
            package (str): Package name ('check_lib.check_sub')
            directory (str)['']: Additional directory path.
            recursive (bool)[False]: If True iterate through subdirectories and find all files.
            extensions (list/str)[None]: List of extensions to register (".csv", ".txt", "" for "LICENSE" with no ext).
                If None register all.
            exclude (list/str)[None]: List of filenames to exclude.
            **kwargs (dict): Dictionary of keyword arguments to set as attributes to the resource.

        Returns:
            directory (list): List of Resource objects that were registered.
        """
        if isinstance(extensions, str):
            extensions = [extensions]
        if exclude is None:
            exclude = []
        elif isinstance(exclude, str):
            exclude = [exclude]
        directory = directory or ''

        folder = []
        pkg = files(package).joinpath(directory)
        if directory or recursive:
            if recursive:
                iter_dir = pkg.glob('**/*')
            else:
                iter_dir = pkg.iterdir()
            for f in iter_dir:
                name = str(f.relative_to(pkg))
                ext = os.path.splitext(name)[-1]
                if not f.is_dir() and (name not in exclude) and (extensions is None or ext in extensions):
                    path = os.path.join(directory, name).replace('\\', '/')  # Normalize path with the directory
                    folder.append(self.register(package, path, **kwargs))
        else:
            for name in contents(package):
                name = str(name)
                ext = os.path.splitext(name)[-1]
                f = pkg.joinpath(name)
                if not f.is_dir() and (name not in exclude) and (extensions is None or ext in extensions):
                    folder.append(self.register(package, name, **kwargs))

        return folder

    def unregister(self, rsc=None, name=None, alias=None):
        """Unregister a resource.

        Args:
            rsc (str/Resource)[None]: Resource to unregister or package name (with name argument) or alias.
            name (str)[None]: Required if package name given
            alias (str)[None]: Alias name identifier to find. This may also be given as first argument.

        Returns:
            rsc (Resource): Resource that was found

        Raises:
            error (ResourceNotAvailable): Resource was not found!
        """
        if isinstance(rsc, str) and isinstance(name, str):
            rsc = '/'.join((rsc.replace('.', '/'), name))
        elif isinstance(alias, str):
            rsc = alias

        for i in reversed(range(len(self))):
            resource = self[i]
            if resource == rsc:
                return self.pop(i)

        raise ResourceNotAvailable('Resource not found! If "package" given then the "name" argument is required.')

    def has_resource(self, rsc=None, name=None, alias=None):
        """Return if the registered resource exists (this can be the alias, resource, or package_path."""
        if isinstance(rsc, str) and isinstance(name, str):
            rsc = '/'.join((rsc.replace('.', '/'), name))
        elif isinstance(alias, str):
            rsc = alias

        return rsc in self

    def get_resources(self, include_managers=True, allow_duplicates=False, rsc_list=None):
        """Return a list of registered resources.

        If multiple resources have the same alias the last one will be used.

        Args:
            include_managers (bool)[True]: If True include sub manager items.
            allow_duplicates (bool)[False]: If True return all resources and do not check for duplicate aliases.
            rsc_list (list)[None]: Current list of resources to add to.
        """
        if rsc_list is None:
            rsc_list = []

        for rsc in reversed(self):
            if allow_duplicates or rsc not in rsc_list:
                rsc_list.append(rsc)

        if include_managers and getattr(self, 'managers', None):
            for man in reversed(self.managers):
                man.get_resources(include_managers=True, allow_duplicates=allow_duplicates, rsc_list=rsc_list)

        return rsc_list

    def get_resource(self, rsc, fallback=None, default=MISSING):
        """Return the found Resource object from the given resource, fallback, or default value.

        Args:
            rsc (str/Resource): Alias name identifier, package path, or Resource object that has a registered resource
            fallback (str)[None]: Fallback alias if the given alias was not registered.
            default (object)[MISSING]: Default value to return if the alias and fallback were not found.

        Returns:
            rsc (Resource): The found Resource object.
        """
        # Try finding the identifier
        try:
            return self[rsc]
        except (KeyError, IndexError, ResourceNotAvailable, Exception):
            pass

        # Try fallback
        try:
            if isinstance(fallback, Resource):
                return fallback
            return self[fallback]
        except (KeyError, IndexError, ResourceNotAvailable, Exception):
            pass

        # Check default
        if default is MISSING:
            raise ResourceNotAvailable('Resource "{}" not found'.format(rsc))
        return default

    def get_binary(self, rsc, fallback=None, default=MISSING):
        """Return the binary data for the Resource object from the given identifier or default.

        Args:
            rsc (str/Resource): Alias name identifier, package path, or Resource object that has a registered resource
            fallback (str)[None]: Fallback alias if the given alias was not registered.
            default (object)[MISSING]: Default value to return if the alias and fallback were not found.

        Returns:
            data (bytes): Binary data that was read.
        """
        rsc = self.get_resource(rsc, fallback, default)
        if isinstance(rsc, Resource):
            return rsc.read_binary()
        return rsc

    def get_text(self, rsc, fallback=None, default=MISSING, encoding='utf-8', errors='strict'):
        """Return the text data for the Resource object from the given identifier or default.

        Args:
            rsc (str/Resource): Alias name identifier, package path, or Resource object that has a registered resource
            fallback (str)[None]: Fallback alias if the given alias was not registered.
            default (object)[MISSING]: Default value to return if the alias and fallback were not found.
            encoding (str)['utf-8']: Encoding to convert binary data to text.
            errors (str)['strict']: Error handling code when converting the binary data to text.

        Returns:
            text (str): Text data that was read.
        """
        rsc = self.get_resource(rsc, fallback, default)
        if isinstance(rsc, Resource):
            return rsc.read_text(encoding=encoding, errors=errors)
        return rsc


class ResourceManager(list, ResourceManagerInterface):

    RESOURCE_CLASS = Resource

    def __init__(self, *resources, **kwargs):
        list.__init__(self)
        ResourceManagerInterface.__init__(self, *resources, **kwargs)

    __iter__ = list.__iter__

    def __contains__(self, item):
        if list.__contains__(self, item):
            return True

        # Search through all linked managers
        for man in reversed(self.managers):
            if item in man:
                return True

        return False

    def __getitem__(self, item):
        if isinstance(item, int):
            return list.__getitem__(self, item)

        # Check self first
        for rsc in reversed(self):
            if rsc == item:
                return rsc

        # Search through all linked managers
        for man in reversed(self.managers):
            try:
                return man[item]
            except (KeyError, IndexError, ResourceNotAvailable, Exception):
                pass

        raise ResourceNotAvailable("The requested resource \"{}\" was not found!".format(item))

    def __setitem__(self, key, value):
        if isinstance(key, int):
            list.__setitem__(self, key, value)
            return
        elif isinstance(key, self.RESOURCE_CLASS):
            key = key.alias or key.package_path

        # Find the resource and replace the identifier
        for i in reversed(range(len(self))):
            rsc = self[i]
            if rsc.alias == key:
                list.__setitem__(i, value)
                return

        # If not found add the resource to the list.
        self.append(value)

    def append(self, resource):
        if hasattr(resource, 'manager') and resource.manager is None:
            resource.manager = self
        return list.append(self, resource)

    pop = list.pop


RESOURCE_MANAGER = ResourceManager()


def get_global_manager():
    """Return the global ResourceManager."""
    global RESOURCE_MANAGER
    return RESOURCE_MANAGER


def set_global_manager(manager):
    """Set the global ResourceManager."""
    global RESOURCE_MANAGER
    RESOURCE_MANAGER = manager


@contextlib.contextmanager
def temp_manager(manager):
    """Temporarily change the global resource manager using this with context."""
    old = get_global_manager()
    set_global_manager(manager)
    try:
        yield
    finally:
        set_global_manager(old)


def add_manager(man):
    """Add a manager to help with saving all managers."""
    return get_global_manager().add_manager(man)


def remove_manager(man):
    """Remove a linked manager."""
    return get_global_manager().remove_manager(man)


def clear():
    """Clear out all of the resources that are registered."""
    get_global_manager().clear()


def register(package, name, alias=MISSING, **kwargs):
    """Register a resource. You can optionally have an alias name identifier.
    When using the alias the last resource registered with the same alias will be used.

    Args:
        package (str): Package name ('check_lib.check_sub')
        name (str): Name of the resource ('edit-cut.png')
        alias (str)[MISSING]: Shortcut alias name identifer for the resource.
            ... (Ellipsis) will be the name with the extension (EX: "myimg.png")
            None will be the name without the extension (EX: "myimg")
        **kwargs (dict): Dictionary of keyword arguments to set as attributes to the resource.
    """
    return get_global_manager().register(package, name, alias=alias, **kwargs)


def register_data(data, package, name, alias=MISSING, **kwargs):
    """Register a plain data resource.

    Args:
        data (bytes/str/object)[None]: Plain data to store.
        package (str)[None]: Package name ('check_lib.check_sub')
        name (str)[None]: Name of the resource ('edit-cut.png')
        alias (str)[MISSING]: Shortcut alias name identifer for the resource.
            ... (Ellipsis) will be the name with the extension (EX: "myimg.png")
            None will be the name without the extension (EX: "myimg")
        **kwargs (dict): Dictionary of keyword arguments to set as attributes to the resource.
    """
    return get_global_manager().register_data(data, package, name, alias=alias, **kwargs)


def register_directory(package, directory='', recursive=False, extensions=None, exclude=None, **kwargs):
    """Register all items in a directory.

    Note:
        This does not register the __init__.py module.

    Args:
        package (str): Package name ('check_lib.check_sub')
        directory (str)['']: Additional directory path.
        recursive (bool)[False]: If True iterate through subdirectories and find all files.
        extensions (list/str)[None]: List of extensions to register (".csv", ".txt", "" for "LICENSE" with no ext).
            If None register all.
        exclude (list/str)[None]: List of filenames to exclude.
        **kwargs (dict): Dictionary of keyword arguments to set as attributes to the resource.

    Returns:
        directory (list): List of Resource objects that were registered.
    """
    return get_global_manager().register_directory(package, directory=directory, recursive=recursive,
                                                   extensions=extensions, exclude=exclude, **kwargs)


def register_resource(rsc, **kwargs):
    """Register a resource.

    Args:
        rsc (Resource): Resource object to register and access later.

    Returns:
        rsc (Resource): Resource object that was registered
    """
    return get_global_manager().register_resource(rsc, **kwargs)


def unregister(rsc=None, name=None, alias=None):
    """Unregister a resource.

    Args:
        rsc (str/Resource)[None]: Resource to unregister or package name (with name argument) or alias.
        name (str)[None]: Required if package name given
        alias (str)[None]: Alias name identifier to find. This may also be given as first argument.

    Returns:
        rsc (Resource): Resource that was found

    Raises:
        error (ResourceNotAvailable): Resource was not found!
    """
    return get_global_manager().unregister(rsc=rsc, name=name, alias=alias)


def has_resource(rsc=None, name=None, alias=None):
    """Return if the registered resource exists (this can be the alias, resource, or package_path."""
    return get_global_manager().has_resource(rsc=rsc, name=name, alias=alias)


def get_resources(include_managers=True, allow_duplicates=False, rsc_list=None):
    """Return a list of registered resources.

    If multiple resources have the same alias the last one will be used.
    """
    return get_global_manager().get_resources(include_managers=include_managers, allow_duplicates=allow_duplicates,
                                              rsc_list=rsc_list)


def get_resource(rsc, fallback=None, default=MISSING):
    """Return the found Resource object from the given resource, fallback, or default value.

    Args:
        rsc (str/Resource): Alias name identifier, package path, or Resource object that has a registered resource
        fallback (str)[None]: Fallback alias if the given alias was not registered.
        default (object)[MISSING]: Default value to return if the alias and fallback were not found.

    Returns:
        rsc (Resource): The found Resource object.
    """
    return get_global_manager().get_resource(rsc, fallback=fallback, default=default)


def get_binary(rsc, fallback=None, default=MISSING):
    """Return the binary data for the Resource object from the given identifier or default.

    Args:
        rsc (str/Resource): Alias name identifier, package path, or Resource object that has a registered resource
        fallback (str)[None]: Fallback alias if the given alias was not registered.
        default (object)[MISSING]: Default value to return if the alias and fallback were not found.

    Returns:
        data (bytes): Binary data that was read.
    """
    return get_global_manager().get_binary(rsc, fallback=fallback, default=default)


def get_text(rsc, fallback=None, default=MISSING, encoding='utf-8', errors='strict'):
    """Return the text data for the Resource object from the given identifier or default.

    Args:
        rsc (str/Resource): Alias name identifier, package path, or Resource object that has a registered resource
        fallback (str)[None]: Fallback alias if the given alias was not registered.
        default (object)[MISSING]: Default value to return if the alias and fallback were not found.
        encoding (str)['utf-8']: Encoding to convert binary data to text.
        errors (str)['strict']: Error handling code when converting the binary data to text.

    Returns:
        text (str): Text data that was read.
    """
    return get_global_manager().get_text(rsc, fallback=fallback, default=default, encoding=encoding, errors=errors)


def registered_datas(resource_manager=None, use_dest_dirs=True,
                     include_managers=True, allow_duplicates=False, rsc_list=None):
    """Return a list of datas that were registered.

    Args:
        resource_manager (ResourceManager)[None]: Resource manger to use. If None use default global ResourceManager.
        use_dest_dirs (bool)[True]: If True the destination will be a directory. If False the dest will be the filename.

    Returns:
        datas (list): List of (existing file path, rel install path).
    """
    if resource_manager is None:
        resource_manager = get_global_manager()

    datas = []

    for man in [resource_manager] + resource_manager.managers:
        for resource in man.get_resources(include_managers=include_managers,
                                          allow_duplicates=allow_duplicates, rsc_list=rsc_list):
            if resource.is_resource():
                with resource.as_file() as rsc_file:
                    package_path = str(resource.package_path)
                    if use_dest_dirs:
                        package_path = os.path.dirname(package_path)
                    data = (os.path.relpath(str(rsc_file)), package_path)
                    if data not in datas:
                        datas.append(data)

    return datas
