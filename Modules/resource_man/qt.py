import os
import sys
import argparse
from pathlib import Path
import importlib
from contextlib import contextmanager
from collections import OrderedDict
from dynamicmethod import dynamicmethod
from qtpy import API_NAME, QtCore, QtGui, QtSvg


try:
    from subprocess import run
except (ImportError, Exception):
    from subprocess import Popen

    def run(*args, check=False, **kwargs):
        proc = Popen(*args, **kwargs)
        proc.wait()
        if check and proc.returncode != 0:
            raise RuntimeError('The program failed to run properly')
        return proc

from resource_man.__meta__ import version as __version__
from resource_man.importlib_interface import \
    READ_API, FILES_API, Traversable, contents, is_resource, read_binary, read_text, files, as_file
from resource_man.interface import \
    ResourceNotAvailable, Resource, ResourceManagerInterface, ResourceManager, \
    get_global_manager, set_global_manager, temp_manager, add_manager, remove_manager, \
    clear, register_resource, register, register_data, register_directory, unregister, has_resource, \
    get_resources, get_resource, get_binary, get_text, registered_datas, \
    MISSING


is_py2 = sys.version_info < (3, 0)

# Qt rcc compiler path
QT_RCC_BIN = files(API_NAME).joinpath('rcc.exe')
if not QT_RCC_BIN.exists():
    QT_RCC_BIN = files(API_NAME).joinpath(API_NAME.lower() + '-rcc.exe')
try:
    if 'PyQt' in API_NAME:
        # pyrcc5 binary
        QT_RCC_BIN = 'pyrcc' + ''.join(c for c in API_NAME if c.isdigit())
except (ValueError, Exception):
    pass


__all__ = [
    'QFile', 'QPixmap', 'QIcon', 'QSvgWidget', 'create_qrc', 'compile_qrc', 'create_compiled', 'load_resource',
    'compiled_py_to_qtpy',

    'READ_API', 'FILES_API', 'Traversable', 'contents', 'is_resource', 'read_binary', 'read_text', 'files', 'as_file',

    'ResourceNotAvailable', 'Resource', 'ResourceManagerInterface', 'ResourceManager',
    'get_global_manager', 'set_global_manager', 'temp_manager', 'add_manager', 'remove_manager',
    'clear', 'register_resource', 'register', 'register_data', 'register_directory', 'unregister',
    'has_resource', 'get_resources', 'get_resource', 'get_binary', 'get_text', 'registered_datas',
    'MISSING',
    '__version__'
    ]


class _ResourceExt(Resource):
    @property
    def qt_name(self):
        """Return the shortcut name used in the compiled qrc file.
        This is not a part of the standard api and should not be used.
        """
        prefix = getattr(getattr(self, 'manager', None), 'prefix', None)
        if prefix:
            return ':/{prefix}/{alias}'.format(prefix=prefix, alias=self.alias)
        return ':/' + self.alias

    orig_eq = Resource.orig_eq = Resource.__eq__  # NEED Resource.orig_eq to be set as well.

    def __eq__(self, other):
        if isinstance(other, str):
            return other == self.qt_name or \
                   other == self.alias or \
                   other.replace('\\', '/') == self.package_path
        return self.orig_eq(other)


# Override Resource methods and properties to work like ResourceExt
Resource.qt_name = _ResourceExt.qt_name
Resource.__eq__ = _ResourceExt.__eq__  # This will help ResourceManager.has_resource and get_resource


QtCore_QFile = QtCore.QFile
QtGui_QIcon = QtGui.QIcon
QtGui_QPixmap = QtGui.QPixmap


def get_file(name, return_bytes=True, extension=None):
    """Return the Qt file name or binary data from the file.

    Args:
        name (str/bytes/Traversable/Resource): Find the file from the name or resource object.
        return_bytes (bool)[True]: If name is Traversable or Resource try reading the bytes.
            If False return Traversable.
        extension (str)[None]: If given str check the extension before returning a valid value.

    Returns:
        name (str/bytes/Traversable): Prefer returning the string filename.
            If unable to find the filename and return_bytes is True return the file bytes.
            If unable to find the filename and return_bytes is False return the Traversable (Path) object.
            If not found or the filename does not have the proper extension return ''.
    """
    file = QFile(name)
    if extension is not None and file.extension() != extension:
        return None
    filename = file.fileName()
    if filename is not None:

        return filename
    elif return_bytes:
        return file.read_bytes()


class QFile(QtCore_QFile):
    def __new__(cls, name=None, parent=None):
        if isinstance(name, QtCore.QObject):
            parent = name
            name = None

        obj = QtCore_QFile.__new__(cls, 'None', parent)
        obj._byts = None
        obj._filename = None
        obj._resource = None
        obj.given_name = name

        return obj

    def __init__(self, name=None, parent=None):
        super().__init__()

        if isinstance(name, QFile):  # This class
            self._byts = getattr(self, '_byts', None)
            self._filename = getattr(self, '_filename', None)
            self._resource = getattr(self, '_resource', None)
            self.given_name = getattr(self, 'given_name', None)
        elif isinstance(name, (bytes, str, Resource, Traversable, Path)):
            self.setFileName(name)

        # name = self.given_name
        # byts = self._byts
        # filename = self._filename
        # resource = self._resource

    # ===== QFile methods =====
    @dynamicmethod
    def exists(self, name=None):
        if isinstance(self, QtCore_QFile):
            if self._byts:
                return True

            has_resource = self._resource and (QtCore_QFile.exists(self._resource.qt_name) or
                                               self._resource.is_resource())
            has_filename = self._filename and QtCore_QFile.exists(self._filename)
            return has_resource or has_filename or \
                   QtCore_QFile.exists(QtCore_QFile.fileName(self))  # super() will crash. Check the filename
        return type(self)(name).exists()

    def basename(self):
        """Return the resource basename."""
        try:
            if self._resource:
                return self._resource.name
            return os.path.basename(self._filename)
        except (TypeError, ValueError):
            return ''

    def extension(self):
        """Return the extension of the resource name or filename."""
        ext = os.path.splitext(self.basename())[-1]
        return ext

    def fileName(self):
        return self._filename

    def setFileName(self, name):
        self._filename = None
        self._byts = None
        self._resource = None
        if isinstance(name, bytes):
            self._byts = name
        elif isinstance(name, Resource):
            self._resource = name
            self._filename = str(self._resource)
            self._byts = self._resource.read_bytes()
        elif isinstance(name, Traversable):
            self._byts = name.read_bytes()
        else:
            # Try to create the icon from the Qt name
            str_name = str(name)

            # Try to create the icon from the registered resource name
            try:
                self._resource = get_resource(str_name)
                if self._filename is None:
                    if QtCore_QFile.exists(self._resource.alias):
                        self._filename = self._resource.alias
                    elif QtCore_QFile.exists(self._resource.qt_name):
                        self._filename = self._resource.qt_name

                    # Try reading the binary data
                    self._byts = self._resource.read_bytes()
            except (ResourceNotAvailable, TypeError, ValueError, OSError, ImportError, Exception):
                pass

            # Try to find the filename from the qt_name
            try:
                if self._filename is None:
                    qt_name = ':/' + str_name
                    if QtCore_QFile.exists(str_name):
                        self._filename = str_name
                    elif QtCore_QFile.exists(qt_name):
                        self._filename = qt_name
            except (ResourceNotAvailable, TypeError, ValueError, Exception):
                pass

        if self._filename is None:
            return super(QFile, self).setFileName('None')
        else:
            return super(QFile, self).setFileName(self._filename)

    def rename(self, newName):
        ret = super(QFile, self).rename(newName)
        if ret:
            self._filename = newName
        return ret

    # ===== QBuffer methods =====
    def data(self):
        if self.byts is not None:
            return QtCore.QByteArray(self.byts)
        return QtCore.QByteArray()

    def setData(self, data):
        self.byts = None
        if data is not None:
            self.byts = bytes(data)

    buffer = data
    setBuffer = setData

    # ===== Resource methods =====
    @property
    def package(self):
        """Return the resource package."""
        try:
            return self._resource.package
        except (AttributeError, Exception):
            return None

    @property
    def name(self):
        """Return the resource name."""
        try:
            return self._resource.name
        except (AttributeError, Exception):
            return None

    @property
    def package_path(self):
        """Return the package and name path of the resource."""
        try:
            return self._resource.package_path
        except (AttributeError, Exception):
            return ''

    @property
    def alias(self):
        """Return the alias name identifier."""
        try:
            return self._resource.alias
        except (AttributeError, Exception):
            return self.fileName()

    # Backwards compatibility support
    identifier = alias

    def is_resource(self):
        try:
            return self._resource.is_resource()
        except (AttributeError, Exception):
            return False

    def files(self):
        return self._resource.files()

    @contextmanager
    def as_file(self):
        with as_file(self.files()) as file:
            yield file

    def contents(self):
        return self._resource.contents()

    def read_bytes(self):
        """Return the read bytes."""
        if self._byts is None and self._resource is not None:
            self._byts = self._resource.read_bytes()
        elif self._byts is None and self._filename is not None:
            try:
                with open(self._filename, 'rb') as f:
                    self._byts = f.read()
            except OSError:
                if self._filename.startswith(':/'):
                    if self.open(self.ReadOnly | self.Text):
                        self._byts = bytes(self.readAll())
                        self.close()

        if self._byts is None:
            raise ResourceNotAvailable('Invalid resource!')
        return self._byts

    read_binary = read_bytes

    def read_text(self, encoding='utf-8', errors='strict'):
        return self.read_bytes().decode(encoding, errors)


class QPixmap(QtGui_QPixmap):
    """Special QPixmap that can load from resource_man values."""
    def __new__(cls, *args, **kwargs):
        return super(QPixmap, cls).__new__(cls)

    def __init__(self, *args, **kwargs):
        load_data = None
        if len(args) >= 1 and isinstance(args[0], (Resource, str, bytes, Traversable)):
            # Try to find filename, Qt File, or importlib.resources read resource bytes.
            file = QFile(args[0])
            args = ('',) + args[1:]
            if file.exists():
                load_data = file.read_bytes()

        super(QPixmap, self).__init__(*args, **kwargs)

        if isinstance(load_data, bytes):
            self.loadFromData(load_data)


class QIcon(QtGui_QIcon):
    """Special QIcon that can load from resource_man values."""
    def __new__(cls, *args, **kwargs):
        obj = super(QIcon, cls).__new__(cls)
        obj.is_valid = False
        return obj

    def __init__(self, *args, **kwargs):
        is_valid = False
        if len(args) >= 1:
            if isinstance(args[0], str) and QIcon.hasThemeIcon(args[0]):
                args = (QtGui_QIcon.fromTheme(args[0]),) + args[1:]
                is_valid = True
            elif isinstance(args[0], (Resource, str, bytes, Traversable)):
                # Try to find filename, Qt File, or importlib.resources read resource bytes.
                file = QFile(args[0])
                args = ('',) + args[1:]
                if file.exists():
                    pixmap = QtGui_QPixmap()
                    pixmap.loadFromData(file.read_bytes())
                    args = (pixmap, ) + args[1:]
                    is_valid = True

        super(QIcon, self).__init__(*args, **kwargs)
        self.is_valid = is_valid

    def isNull(self, *args, **kwargs):
        return not self.is_valid and super().isNull()

    @dynamicmethod
    def fromTheme(self, name, fallback=None):
        icn = QIcon(name)
        if not icn.is_valid and fallback is not None:
            icn = QIcon(fallback)

        if isinstance(self, QIcon):
            self.swap(icn)
            return self
        return icn


QtSvgWidgets = None
if not hasattr(QtSvg, "QSvgWidget"):
    try:
        if API_NAME == 'PyQt6':
            from PyQt6 import QtSvgWidgets
        elif API_NAME == 'PyQt5':
            from PyQt5 import QtSvgWidgets
        elif API_NAME == 'PySide6':
            from PySide6 import QtSvgWidgets
        elif API_NAME == 'PySide2':
            from PySide2 import QtSvgWidgets
        ORIG_QSvgWidget = QtSvgWidgets.QSvgWidget
    except (ImportError, Exception):
        class ORIG_QSvgWidget:
            def __new__(cls, *args, **kwargs):
                raise EnvironmentError('Could not load the proper SVG Widget. '
                                       'This version of Qt may not be supported')

else:
    ORIG_QSvgWidget = QtSvg.QSvgWidget


class QSvgWidget(ORIG_QSvgWidget):
    """QSvgWidget with resource_man support."""
    def __new__(cls, *args, **kwargs):
        return super(QSvgWidget, cls).__new__(cls)

    def __init__(self, *args, **kwargs):
        load_data = None
        if len(args) >= 1 and isinstance(args[0], (Resource, str, bytes, Traversable)):
            # Try to find filename, Qt File, or importlib.resources read resource bytes.
            file = QFile(args[0])
            args = ('',) + args[1:]
            if file.exists() and file.extension().lower() == '.svg':
                load_data = file.read_bytes()

        super(QSvgWidget, self).__init__(*args, **kwargs)

        if isinstance(load_data, bytes):
            self.load(load_data)


@contextmanager
def context_file(file):
    """Use as_file or just yield the given file."""
    if isinstance(file, Traversable):
        with as_file(file) as fname:
            yield fname
    else:
        yield file


def create_qrc(filename="resource_man_compiled_resources.qrc", prefix='', resource_manager=None, main_module=None):
    """Make a Qt RCC file.

    Note:
        This registers the resource with an alias shortcut identifier.

        .. code-block:: python

            >>> resource_man.register('check_lib.check_sub', 'edit-cut.png', alias='edit-cut')

        The alias can be used with QIcon(":/edit-cut")

    Example:
        .. code-block:: python

            >>> import resource_man.qt as resource_man
            >>>
            >>> resource_man.register('check_lib.check_sub', 'edit-cut.png', 'edit-cut')
            >>>
            >>> resource_man.create_qrc()  # app_resources.qrc created

    Args:
        filename (str)['resource_man_compiled_resources.qrc']: Filename to create the .qrc file with.
        prefix (str)['']: qresource prefix.
        resource_manager (ResourceManager)[None]: Resource manger to use. If None use default global ResourceManager.
        main_module (str)[None]: This module will be imported to register resources before creating the .qrc file.

    Returns:
        filename (str): Absolute path of the filename that was written.
    """
    if resource_manager is None:
        resource_manager = get_global_manager()

    # Import the main module that registers the resources
    if isinstance(main_module, (str, Path)):
        main_module = str(main_module)
        if '/' in main_module or '\\' in main_module or '.' in main_module:
            sys.path.append(os.path.dirname(main_module))
            main_module = os.path.splitext(os.path.basename(main_module))[0]
        importlib.import_module(main_module)

    # Get all managers according to their prefix
    managers = OrderedDict([(None, [])])
    prefix = prefix or getattr(resource_manager, 'prefix', None) or None
    try:
        managers[prefix].append(resource_manager)
    except (KeyError, AttributeError, Exception):
        managers[prefix] = [resource_manager]
    for man in resource_manager.managers:
        prefix = getattr(man, 'prefix', None) or None
        try:
            managers[prefix].append(man)
        except (KeyError, AttributeError, Exception):
            managers[prefix] = [man]

    # Create the QRC File
    text = ['<!DOCTYPE RCC><RCC version="1.0">']

    for prefix, mans in managers.items():
        if prefix:
            text.append('<qresource prefix="{}">'.format(prefix))
        else:
            text.append('<qresource>')

        for man in mans:
            for resource in man.get_resources():
                if resource.is_resource():
                    with resource.as_file() as rsc_file:
                        path = os.path.relpath(str(rsc_file))
                        text.append('\t<file alias="{}">{}</file>'.format(resource.alias, path))

        text.append('</qresource>')

    text.append('</RCC>')

    with open(filename, "w") as file:
        file.write("\n".join(text))

    return os.path.abspath(filename)


def compile_qrc(filename="resource_man_compiled_resources.qrc", output=None, rcc_bin=QT_RCC_BIN, use_qtpy=True):
    """Create the python resource file from the .qrc file.

    Args:
        filename (str)['resource_man_compiled_resources.qrc']: QRC resrouce file.
        output (str)[None]: Name of the new python file that should be created.
            Default "resource_man_compiled_resources.py" or "resource_man_compiled_resources.rcc".
        rcc_bin (Traversable/Path/str)[files(API_NAME).joinpath(rcc.exe)]: Path to the rcc binary.
        use_qtpy (bool)[True]: If True replace the Qt API with qtpy.

    Returns:
        filename (str): Python filename of the saved resource file.
    """
    if output is None:
        output = os.path.splitext(filename)[0] + ".py"  # or .py and "import app_resources.py"

    with context_file(rcc_bin) as rcc:
        rcc = str(rcc)
        args = [rcc, filename, '-o', output]
        is_py = not output.endswith('.rcc')
        is_pyqt = 'pyrcc' in rcc
        is_old_pyside = 'pyside-rcc' in rcc
        is_pyside = not is_pyqt and not is_old_pyside

        if is_pyside:  # Pyside2+
            # If .py file and PySide2+ you need "-g python" arguments
            if is_py:
                args.extend(['-g', 'python'])
            else:
                # .rcc binary file for pyside
                args.append('-binary')
        elif is_old_pyside:
            # .rcc binary file for PySide is not supported
            if not is_py:
                args[3] = output = os.path.splitext(output)[0] + '.py'  # PySide rcc does not support rcc binary

            # Need to identify the python version
            if is_py2:
                args.append('-py2')
            else:
                args.append('-py3')
        elif is_pyqt and not is_py:
            # .rcc binary file for PyQt is not supported
            args[3] = output = os.path.splitext(output)[0] + '.py'  # PyQT rcc does not support rcc binary

        success = run(args, stdout=sys.stdout, stderr=sys.stderr).returncode == 0
        if success and is_py and use_qtpy:
            compiled_py_to_qtpy(output)

        return output


def compiled_py_to_qtpy(filename):
    """Modify the compiled .py file to use qtpy instead of PySide2 or PyQt5."""
    # Convert resources.py import of PySide2 or PyQt5 to qtpy
    with open(filename, 'r+') as f:
        lines = f.readlines()
        f.seek(0, 0)
        f.truncate()  # File size is not different must truncate

        # Cannot use f.read().replace(API_NAME, 'qtpy') because we allow given rcc_bin
        for i, line in enumerate(lines):
            if ' import QtCore' in line:  # line is "from PySide2 import QtCore"
                lines[i] = 'from qtpy import QtCore\n'  # Does not use Windows \r\n. Otherwise could use os.linesep
                break

        f.writelines(lines)


def create_compiled(filename="resource_man_compiled_resources.qrc", prefix='', main_module=None, output=None,
                    rcc_bin=QT_RCC_BIN, use_qtpy=True):
    """Make a Qt RCC .qrc file, compile the Qt RCC file to a .py or .rcc file, and remove the unneeded QRC file.

    Note:
        This registers the resource with an alias shortcut identifier.

        .. code-block:: python

            >>> resource_man.register('check_lib.check_sub', 'edit-cut.png', 'edit-cut')

        The alias can be used with QIcon(":/edit-cut")

    Example:
        .. code-block:: python

            >>> import resource_man.qt as resource_man
            >>>
            >>> resource_man.register('check_lib.check_sub', 'edit-cut.png', 'edit-cut')
            >>>
            >>> resource_man.create_qrc()  # resource_man_compiled_resources.qrc created
            >>> resource_man.compile_qrc()  # resource_man_compiled_resources.py created
            >>> os.remove('resource_man_compiled_resources.qrc')

    Args:
        filename (str)['resource_man_compiled_resources.qrc']: Filename to create the .qrc file with.
        prefix (str)['']: qresource prefix.
        main_module (str)[None]: This module will be imported to register resources before creating the .qrc file.
        output (str)[None]: Name of the new python file that should be created.
            Default "resource_man_compiled_resources.py" or "resource_man_compiled_resources.rcc".
        rcc_bin (Traversable/Path/str)[files(API_NAME).joinpath(rcc.exe)]: Path to the rcc binary.
        use_qtpy (bool)[True]: If True replace the Qt API with qtpy.

    Returns:
        filename (str): Python filename of the saved resource file.
    """
    create_qrc(filename, prefix=prefix, main_module=main_module)
    out = compile_qrc(filename, output=output, rcc_bin=rcc_bin, use_qtpy=use_qtpy)
    os.remove(filename)
    return out


def load_resource(filename='resource_man_compiled_resources.py'):
    """Load a Qt resource file."""
    try:
        if filename == 'resource_man_compiled_resources.py':
            import resource_man_compiled_resources
            return True
    except (ImportError, Exception):
        pass

    try:
        # Try to use a resource file path
        with context_file(filename) as fname:
            fname = str(fname)
            if fname.endswith('.rcc'):
                return QtCore.QResource.registerResource(fname)
            else:
                directory = os.path.dirname(fname)
                dir_added = directory not in sys.path  # Could convert to := later. Want to support backwards compatible
                if dir_added:
                    sys.path.append(directory)
                try:
                    importlib.import_module(os.path.splitext(os.path.basename(fname))[0])
                finally:
                    if dir_added:
                        sys.path.remove(directory)
                return True
    except (ImportError, Exception):
        return False


if __name__ == '__main__':
    P = argparse.ArgumentParser('Run a Qt resource helper.')

    # ===== Sub commands =====
    SUBP = P.add_subparsers(help='Qt Resource commands.')

    # Create QRC
    CREATE_QRC = SUBP.add_parser('create', help='Create the .qrc file.')
    CREATE_QRC.set_defaults(func=create_qrc)
    # Main module to import
    CREATE_QRC.add_argument('main_module', type=str, help='Main module that is imported and registers resources.')
    CREATE_QRC.add_argument('--filename', '-f', type=str, default='resource_man_compiled_resources.qrc')
    CREATE_QRC.add_argument('--prefix', '-p', type=str, default='')

    # Compile QRC
    COMPILE_QRC = SUBP.add_parser('compile', help='Compile the .qrc file into an importable .py file of binaries.')
    COMPILE_QRC.set_defaults(func=compile_qrc)
    COMPILE_QRC.add_argument('--filename', '-f', type=str, default='resource_man_compiled_resources.qrc')
    COMPILE_QRC.add_argument('--output', '-o', type=str, default=None)
    COMPILE_QRC.add_argument('--rcc_bin', type=str, default=QT_RCC_BIN)
    COMPILE_QRC.add_argument('--use_qtpy', '-q', type=bool, default=True, help='Convert compiled resources to qtpy.')

    # Run both
    RUN_P = SUBP.add_parser('run', help='Create and compile the resources.')
    RUN_P.set_defaults(func=create_compiled)
    # Main module to import
    RUN_P.add_argument('main_module', type=str, help='Main module that is imported and registers resources.')
    RUN_P.add_argument('--filename', '-f', type=str, default='resource_man_compiled_resources.qrc')
    RUN_P.add_argument('--prefix', '-p', type=str, default='')
    RUN_P.add_argument('--output', '-o', type=str, default=None)
    RUN_P.add_argument('--rcc_bin', type=str, default=QT_RCC_BIN)
    RUN_P.add_argument('--use_qtpy', '-q', type=bool, default=True, help='Convert compiled resources to qtpy.')

    # ===== Parse given command line arguments into keyword arguments =====
    ARGS, REMAIN = P.parse_known_args()
    KWARGS = {name: getattr(ARGS, name, None) for name in dir(ARGS) if not name.startswith('_')}

    # ===== Run the subcommand =====
    FUNC = KWARGS.pop('func')
    FUNC(**KWARGS)
