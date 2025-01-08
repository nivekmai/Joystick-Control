import os
import sys
import platform
import subprocess

from . import config
from .lib import fusionAddInUtils as futil
from adsk.core import LogLevels

def installPygameWindows():
    virtualenvDirName = f"{config.ADDIN_NAME}Venv"
    # Clean up path in case we crashed somewhere, sys should not contain our virtualenv yet
    sys.path = [dir for dir in sys.path if dir.find(virtualenvDirName) == -1]

    original_sys_path = sys.path.copy()

    virtualenv = os.path.join(sys.path[0], virtualenvDirName)
    python = os.path.join(sys.path[0], "Python", "python.exe")
    virtualenvSitePackages = os.path.join(virtualenv, "Lib", "site-packages")

    if not os.path.isdir(virtualenv):
        futil.log(f"{config.ADDIN_NAME}: missing virtualenv, creating...", LogLevels.WarningLogLevel)
        subprocess.check_call([python, '-m', 'venv', virtualenv]) 

    futil.log(f"{config.ADDIN_NAME}: virtualenv exists, attempting to import from virtualenv", LogLevels.InfoLogLevel)
    # in case of script failure, the virtualenv might already be in the path from a previous run
    if not virtualenv in sys.path:
        sys.path.insert(0, virtualenvSitePackages)
    try:
        import pygame
        return(True, original_sys_path.copy())
    except:
        try:
            futil.log(f"{config.ADDIN_NAME}: missing pygame, installing...", LogLevels.WarningLogLevel)
            subprocess.check_call([os.path.join(virtualenv, "Scripts", "pip.exe"), "install", "--upgrade", "pygame"])
            futil.log(f"{config.ADDIN_NAME}: pygame installed", LogLevels.InfoLogLevel)
            return (True, original_sys_path.copy())
        except:
            futil.handle_error("Failed to install and import pygame. See text console for more details", True)
            return (False, original_sys_path.copy())

installedPygame = False

if platform.system() is 'Windows':
    (installedPygame, original_sys_path) = installPygameWindows()
    if installedPygame:
        try:
            import pygame
            futil.log(f"{config.ADDIN_NAME}: pygame installed", LogLevels.InfoLogLevel)
        except:
            futil.handle_error(f"{config.ADDIN_NAME}: Failed to import pygame, falling back to use pyjoystick (less gamepad support). See text console for more details", True)
            installedPygame = False
    sys.path = original_sys_path
else:
    #TODO: figure out where the python executable is on mac
    futil.handle_error("Sorry, this OS is unsupported, falling back to use pyjoystick (less gamepad support)", True)


# pyjoystic must be imported after pygame as it causes dynamic linking issues with SDL2
if not installedPygame:
    from .Modules.pyjoystick.sdl2 import run_event_loop

from .Modules.pyjoystick.interface import KeyTypes, Key, Joystick

from adsk.core import Vector3D, Matrix3D, Application, Point3D, Camera, ViewOrientations
from time import sleep
from math import pow, pi, radians
from adsk import doEvents
from threading import Event, Thread
from typing import Literal

# Special number to tell camera to go orientation home
HOME_ORIENTATION = -1
# Special number to tell the camera to constrain the upVector to a primary axis
CONSTRAIN_ORIENTATION = -2

# Configure as you wish
ZOOM_SCALE = 0.1
PAN_AXIS_SCALE = 0.1
ROTATION_AXIS_SCALE = 0.01
PAN_ZOOM_COMPENSATION = 0.0005
ZOOM_EXTENT_MULTIPLIER = 0.1
AXIS_DEADZONE = 0.15

PAN_X_AXIS = 0
PAN_Y_AXIS = 1
ROTATE_X_AXIS = 3
ROTATE_Y_AXIS = 4
ROTATE_Z_AXIS = 2

HAT_TO_VIEW = {
    Key.HAT_NAME_UP: ViewOrientations.TopViewOrientation,
    Key.HAT_NAME_DOWN: ViewOrientations.BottomViewOrientation,
    Key.HAT_NAME_LEFT: ViewOrientations.LeftViewOrientation,
    Key.HAT_NAME_RIGHT: ViewOrientations.RightViewOrientation,
}
BUTTON_TO_VIEW = {
    0: HOME_ORIENTATION,
    1: ViewOrientations.TopViewOrientation,
    2: CONSTRAIN_ORIENTATION,
}


class PyJoystickThread(Thread):
    """
    pyjoystick's ThreadEventManager doesn't seem to work, so we're just running
    it in our own thread here.
    """

    def __init__(self, event: Event):
        Thread.__init__(self)
        self.stopped = event

    def handle_key_event(self, key: Key):
        """
        Assigns axis values into the global axes variable so the RenderThread
        can pick them up

        Args:
            key (Key): joystick keys
        """
        if key.keytype is KeyTypes.AXIS:
            if key.number < 6:
                axes[key.number] = key.get_proper_value()
            else:
                futil.log(f"{config.ADDIN_NAME}: unknown axis: {key.number}: {key.get_proper_value()}")
        elif key.keytype is KeyTypes.HAT:
            hatCam(key.get_hat_name())
        elif key.keytype is KeyTypes.BUTTON and key.value == 0:
            buttonCam(key.number)

    def add(self, joy: Joystick):
        """
        useless, but pyjoystick doesn't work without it
        """
        return

    def remove(self, joy: Joystick):
        """
        useless, but pyjoystick doesn't work without it
        """
        return

    def run(self):
        try:
            run_event_loop(
                add_joystick=self.add,
                remove_joystick=self.remove,
                handle_key_event=self.handle_key_event,
                alive=alive,
            )
        except:
            pass

class PyGameThread(Thread):
    def __init__(self, event: Event):
        Thread.__init__(self)
        self.stopped = event

    def run(self):
        try:
            self.pygameJoysticks = {}
            while alive():
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.stopped = True  

                    # Handle hotplugging, also initializes the joysticks when plugged in (otherwise we don't get the other events)
                    if event.type == pygame.JOYDEVICEADDED:
                        joy = pygame.joystick.Joystick(event.device_index)
                        self.pygameJoysticks[joy.get_instance_id()] = joy

                    if event.type == pygame.JOYDEVICEREMOVED:
                        del self.pygameJoysticks[event.instance_id]

                    if event.type == pygame.JOYBUTTONDOWN:
                        buttonCam(event.button)

                    if event.type == pygame.JOYHATMOTION:
                        hatCam(pygameToHatName(event.value))

                    if event.type == pygame.JOYAXISMOTION:
                        axes[event.axis] = event.value
        except:
            pass

class RenderThread(Thread):
    """
    Handles translating the current axes into movements of the camera
    """

    def __init__(self, event: Event):
        super().__init__()
        self.stopped = event

    def run(self):
        while alive():
            try:
                moveCamForAxes(
                    panXAxis=getPanXAxis(axes),
                    panYAxis=getPanYAxis(axes),
                    rotateXAxis=getRotateXAxis(axes),
                    rotateYAxis=getRotateYAxis(axes),
                    rotateZAxis=getRotateZAxis(axes),
                )
                sleep(0.01)
            except:
                pass


def run(context):
    try:
        global stopFlag
        global axes
        global app
        app = Application.get()
        axes = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        stopFlag = Event()

        if installedPygame:
            pygame.init()
            pygameJoystickThread = PyGameThread(stopFlag)
            pygameJoystickThread.start()
        else:
            joystickThread = PyJoystickThread(stopFlag)
            joystickThread.start()
        renderThread = RenderThread(stopFlag)
        renderThread.start()

    except:
        futil.handle_error("run")


def stop(context):
    try:
        # Remove all of the event handlers your app has created
        futil.clear_handlers()
        stopFlag.set()

    except:
        futil.handle_error("stop")


def deadZone(axis: float) -> float:
    """
    Check if an axis is inside the AXIS_DEADZONE and return 0 if so.
    """
    if (abs(axis)) < AXIS_DEADZONE:
        return 0
    return axis


def getPanXAxis(axes: list[float]) -> float:
    """
    Get the axis for X panning. Configure this by updating PAN_X_AXIS
    """
    return deadZone(axes[PAN_X_AXIS])


def getPanYAxis(axes: list[float]) -> float:
    """
    Get the axis for Y panning. Configure this by updating PAN_Y_AXIS
    """
    return deadZone(axes[PAN_Y_AXIS])


def getRotateXAxis(axes: list[float]) -> float:
    """
    Get the axis for X rotation. Configure this by updating ROTATE_X_AXIS
    """
    return deadZone(axes[ROTATE_X_AXIS])


def getRotateYAxis(axes: list[float]) -> float:
    """
    Get the axis for Y rotation. Configure this by updating ROTATE_Y_AXIS
    """
    return deadZone(axes[ROTATE_Y_AXIS])

def getRotateZAxis(axes: list[float]) -> float:
    """
    Get the axis for Z rotation. Configure this by updating ROTATE_Z_AXIS
    """
    return deadZone(axes[ROTATE_Z_AXIS])


def hatCam(hatName: str):
    """
    Orient the camera for a given hat direction press
    """
    orientCam(HAT_TO_VIEW.get(hatName))


def buttonCam(button: int):
    """
    Orient the camera for a given button press
    """
    orientCam(BUTTON_TO_VIEW.get(button))


def orientCam(nextOrientation: ViewOrientations | Literal[-1]) -> Camera :
    """
    Orient the activeViewport's camera to the chosen orientation

    Args:
        nextOrientation (int): Should be one of the ViewOrientations, or HOME_ORIENTATION to send the viewport to the configured home
    """
    if nextOrientation is None:
        return
    cam = app.activeViewport.camera
    cam.isSmoothTransition = False
    if nextOrientation == HOME_ORIENTATION:
        app.activeViewport.goHome()
        return
    elif nextOrientation == CONSTRAIN_ORIENTATION:
        upVector = getFrontVector().crossProduct(getLeftVector())
        cam.upVector = getConstrainedVector(upVector)
        cam.isSmoothTransition = True
    else:
        cam.viewOrientation = nextOrientation
    setCam(cam)


def moveCamForAxes(
    panXAxis: float = 0,
    panYAxis: float = 0,
    rotateXAxis: float = 0,
    rotateYAxis: float = 0,
    zoomAxis: float = 0,
    rotateZAxis: float = 0,
) -> None:
    if (
        panXAxis == 0
        and panYAxis == 0
        and rotateXAxis == 0
        and rotateYAxis == 0
        and zoomAxis == 0
        and rotateZAxis == 0
    ):
        return

    cam = app.activeViewport.camera

    horizontalRotationMatrix = Matrix3D.create()
    verticalRotationMatrix = Matrix3D.create()
    tiltRotationMatrix = Matrix3D.create()
    target = cam.target.copy()
    eye = cam.eye.copy()

    frontVector = getFrontVector()
    leftVector = getLeftVector()

    # Update the upVector early during a horizontal rotation before continuing
    # so that other calculations are correct
    horizontalRotationMatrix.setToRotation(
        axisToRadian(rotateYAxis), leftVector, target
    )
    upVector = newUpFromRotationMatrix(cam.upVector, horizontalRotationMatrix)

    tiltRotationMatrix.setToRotation(
        axisToRadian(rotateZAxis), frontVector, target
    )
    upVector = newUpFromRotationMatrix(upVector, tiltRotationMatrix)
    constrainedUpVector = getConstrainedVector(upVector)

    # failed attempts to get the correct upVector
    # upVector = newUpFromInvertedHorizontal(cam, horizontalRotationMatrix)
    # upVector = newUpFromCrossProduct(frontVector, leftVector)
    # upVector = newUpFromRotatedFrontVector(eye, target, leftVector)

    zoomVector = getZoomVector(zoomAxis, frontVector)
    verticalPanVector = getVerticalPanVector(scalePanAxis(panYAxis), upVector)
    horizontalPanVector = getHorizontalPanVector(scalePanAxis(panXAxis), leftVector)

    verticalRotationMatrix.setToRotation(axisToRadian(rotateXAxis), constrainedUpVector, target)

    panVector = horizontalPanVector.copy()
    panVector.add(verticalPanVector)
    panVector.scaleBy(frontVector.length * PAN_ZOOM_COMPENSATION)

    # Translate target and eye to "pan"
    target.translateBy(panVector)
    eye.translateBy(panVector)

    if zoomVector.length > 0:
        eye.translateBy(zoomVector)
        extentVector = target.asVector()
        extentVector.subtract(eye.asVector())
        cam.setExtents(
            extentVector.length * ZOOM_EXTENT_MULTIPLIER,
            extentVector.length * ZOOM_EXTENT_MULTIPLIER,
        )

    # Rotate only the eye
    eye.transformBy(horizontalRotationMatrix)
    eye.transformBy(verticalRotationMatrix)

    # Apply changes
    cam.upVector = upVector
    cam.isSmoothTransition = False
    cam.target = target
    cam.eye = eye
    setCam(cam)


def newUpFromInvertedHorizontal(
    cam: Camera, horizontalRotationMatrix: Matrix3D
) -> Vector3D:
    """
    Doesn't work...

    Idea was to invert the horizontal rotation we used to move the eye and apply
    that to the previous upVector so it rotates in line
    """
    invertedRotation = horizontalRotationMatrix.copy()
    invertedRotation.invert()
    newUp = cam.upVector.copy()
    newUp.transformBy(invertedRotation)
    return newUp


def newUpFromRotationMatrix(
    vector: Vector3D, rotationMatrix: Matrix3D
) -> Vector3D:
    """
    Apply the rotation matrix to the previous upVector
    """
    newUp = vector.copy()
    newUp.transformBy(rotationMatrix)
    return newUp


def newUpFromCrossProduct(frontVector: Vector3D, leftVector: Vector3D) -> Vector3D:
    """
    Doesn't work...

    Idea was to get the cross product from the frontVector and leftVector (which should be the correct up vector?)
    """
    return frontVector.crossProduct(leftVector)


def newUpFromRotatedFrontVector(eye: Point3D, target: Point3D, leftVector: Vector3D):
    """
    Doesn't work...

    Idea was to take the current frontVector and rotate it 90 degress along the leftVector to create a proper upVector
    """
    newUp = eye.vectorTo(target)
    perpendicularMatrix = Matrix3D.create()
    perpendicularMatrix.setToRotation(radians(90), leftVector, eye)
    newUp.transformBy(perpendicularMatrix)


def alive():
    """
    Determine if the add-in is still alive

    Returns:
        bool: if the add-in is alive
    """
    if stopFlag.isSet():
        return False
    return True


def scalePanAxis(axis: float) -> float:
    """
    Scale a pan axis such that it accelerates making 0->1 a nice curve

    Args:
        axis (float): the pan axis as a float

    Returns:
        float: scaled axis to the curve
    """
    return pow(axis / 2 * 10, 3) * PAN_AXIS_SCALE


def axisToRadian(axis: float) -> float:
    """
    Get radians for a given axis

    Args:
        axis (float): the rotation axis as a float

    Returns:
        float: radians to rotate the camera
    """
    return pi * 2 * axis * ROTATION_AXIS_SCALE


def getZoomVector(zoomAxis: float, frontVector: Vector3D) -> Vector3D:
    """
    Get a vector for a zoom movement

    Args:
        zoomAxis (float): the zoom axis as a float
        frontVector (Vector3d): the vector between the eye and target from the camera

    Returns:
        Vector3D: A vector representing how far to move the eye towards the target
    """
    zoomVector = frontVector.copy()
    zoomVector.scaleBy(zoomAxis * ZOOM_SCALE)
    return zoomVector


def getVerticalPanVector(scale: float, upVector: Vector3D) -> Vector3D:
    """
    Get a vertical vector for a pan movement

    Args:
        scaledAxis (float): the vertical pan axis as a float
        upvector (Vector3d): the vector pointing up (expects a constrained vector)

    Returns:
        Vector3D: A vector representing how far to move the camera (eye and target) to pan up/down
    """
    vecV = constrain(upVector.copy())
    vecV.scaleBy(scale)
    return vecV


def getHorizontalPanVector(
    scaledAxis: float,
    leftVector: Vector3D,
) -> Vector3D:
    """
    Get a horizontal vector for a pan movement

    Args:
        scaledAxis (float): the horizontal pan axis as a float
        leftVector (Vector3d): the vector pointing left (expects a constrained vector)

    Returns:
        Vector3D: A vector representing how far to move the camera (eye and target) to pan left/right
    """
    vecH = constrain(leftVector.copy())
    vecH.scaleBy(scaledAxis)
    return vecH


def getFrontVector() -> Vector3D:
    cam = app.activeViewport.camera
    return cam.target.vectorTo(cam.eye)


def getLeftVector() -> Vector3D:
    """
    Get a vector that points left from the current camera view

    Args:
        upVector (Vector3D): vector pointing up from camera view
        target (Point3d): target for the camera view
        eye (Point3d): eye for the camera view

    Returns:
        Vector3D: A left pointing vector
    """
    cam = app.activeViewport.camera
    return cam.upVector.crossProduct(cam.target.vectorTo(cam.eye))


def constrain(vector: Vector3D) -> Vector3D:
    """
    Scale a vector such that the max absolute value of any component will be 1

    Args:
        vector (Vector3D): vector to scale

    Returns:
        Vector3D: A scaled vector
    """
    maxPos = max(vector.asArray())
    maxNeg = abs(min(vector.asArray()))
    maxAbs = max(maxNeg, maxPos)
    vector.scaleBy(1 / maxAbs)
    return vector


def getConstrainedVector(vector) -> Vector3D:
    """
    Get a pure primary direction that the vector is closest to
    """
    absX = abs(vector.x)
    absY = abs(vector.y)
    absZ = abs(vector.z)
    biggest = max(absX, absY, absZ)
    if (biggest == absX):
        if vector.x > 0:
            return Vector3D.create(1, 0, 0)
        return Vector3D.create(-1, 0, 0)
    elif (biggest == absY):
        if vector.y > 0:
            return Vector3D.create(0, 1, 0)
        return Vector3D.create(0, -1, 0)
    else:
        if vector.z > 0:
            return Vector3D.create(0, 0, 1)
        return Vector3D.create(0, 0, -1)


def setCam(cam: Camera):
    """
    Set the activeViewport to the given cam, makes sure to let F360 do it's work to update the view

    Args:
        cam (Camer): camera to set the viewport to
    """
    app.activeViewport.camera = cam
    doEvents()
    app.activeViewport.refresh()

def pygameToHatName(value):
    """
    Convert pygame hat tuple to hat name
    """
    match value:
        case (-1, 0): return Key.HAT_NAME_LEFT
        case (0, 1): return Key.HAT_NAME_UP
        case (1, 0): return Key.HAT_NAME_RIGHT
        case (0, -1): return Key.HAT_NAME_DOWN