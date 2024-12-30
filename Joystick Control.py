from .lib import fusionAddInUtils as futil
from .Modules.pyjoystick.sdl2 import run_event_loop
from .Modules.pyjoystick.interface import KeyTypes, Key, Joystick
from time import sleep
from math import pow, pi, radians
from adsk import doEvents
from adsk.core import Vector3D, Matrix3D, Application, Point3D, Camera, ViewOrientations
from threading import Event, Thread
from typing import Literal

TAG = "JoystickControl/"
# Special number to tell camera to go orientation home
HOME_ORIENTATION = -1

# Configure as you wish
ZOOM_SCALE = 0.1
PAN_AXIS_SCALE = 0.1
ROTATION_AXIS_SCALE = 0.01
PAN_ZOOM_COMPENSATION = 0.0005
ZOOM_EXTENT_MULTIPLIER = 0.1
AXIS_DEADZONE = 0.15
PAN_X_AXIS = 0
PAN_Y_AXIS = 1
ZOOM_POS_AXIS = 2
ROTATE_X_AXIS = 3
ROTATE_Y_AXIS = 4
ZOOM_NEG_AXIS = 5
HAT_TO_VIEW = {
    Key.HAT_NAME_UP: ViewOrientations.TopViewOrientation,
    Key.HAT_NAME_DOWN: ViewOrientations.BottomViewOrientation,
    Key.HAT_NAME_LEFT: ViewOrientations.LeftViewOrientation,
    Key.HAT_NAME_RIGHT: ViewOrientations.RightViewOrientation,
}
BUTTON_TO_VIEW = {
    0: ViewOrientations.FrontViewOrientation,
    1: ViewOrientations.BackViewOrientation,
    2: HOME_ORIENTATION,
}


class JoystickThread(Thread):
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
                futil.log(f"{TAG}unknown axis: {key.number}: {key.get_proper_value()}")
        elif key.keytype is KeyTypes.HAT:
            hatCam(key.get_hat_name())
        elif key.keytype is KeyTypes.BUTTON:
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
                    getPanXAxis(axes),
                    getPanYAxis(axes),
                    getRotateXAxis(axes),
                    getRotateYAxis(axes),
                    getZoomAxis(axes),
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
        joystickThread = JoystickThread(stopFlag)
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
    return deadZone(axes[PAN_Y_AXIS]) * -1


def getRotateXAxis(axes: list[float]) -> float:
    """
    Get the axis for X rotation. Configure this by updating ROTATE_X_AXIS
    """
    return deadZone(axes[ROTATE_X_AXIS])


def getRotateYAxis(axes: list[float]) -> float:
    """
    Get the axis for Y rotation. Configure this by updating ROTATE_Y_AXIS
    """
    return deadZone(axes[ROTATE_Y_AXIS]) * -1


def getZoomAxis(axes: list[float]) -> float:
    """
    Get the axis for zoom. Configure this by updating ZOOM_POS_AXIS and ZOOM_NEG_AXIS
    """
    return deadZone(axes[ZOOM_POS_AXIS] - axes[ZOOM_NEG_AXIS])


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
    cam.viewOrientation = nextOrientation
    setCam(cam)


def moveCamForAxes(
    panXAxis: float = 0,
    panYAxis: float = 0,
    rotateXAxis: float = 0,
    rotateYAxis: float = 0,
    zoomAxis: float = 0,
) -> None:
    if (
        panXAxis == 0
        and panYAxis == 0
        and rotateXAxis == 0
        and rotateYAxis == 0
        and zoomAxis == 0
    ):
        return

    cam = app.activeViewport.camera

    horizontalRotationMatrix = Matrix3D.create()
    verticalRotationMatrix = Matrix3D.create()
    upVector = cam.upVector.copy()
    target = cam.target.copy()
    eye = cam.eye.copy()

    frontVector = getFrontVector()
    leftVector = getLeftVector()

    # Update the upVector early during a horizontal rotation before continuing
    # so that other calculations are correct
    horizontalRotationMatrix.setToRotation(
        axisToRadian(rotateYAxis), leftVector, target
    )
    upVector = newUpFromRotatingHorizontal(cam, horizontalRotationMatrix)

    # failed attempts to get the correct upVector
    # upVector = newUpFromInvertedHorizontal(cam, horizontalRotationMatrix)
    # upVector = newUpFromCrossProduct(frontVector, leftVector)
    # upVector = newUpFromRotatedFrontVector(eye, target, leftVector)

    zoomVector = getZoomVector(zoomAxis, frontVector)
    verticalPanVector = getVerticalPanVector(scalePanAxis(panYAxis), upVector)
    horizontalPanVector = getHorizontalPanVector(scalePanAxis(panXAxis), leftVector)

    verticalRotationMatrix.setToRotation(axisToRadian(rotateXAxis), upVector, target)

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
    eye.transformBy(verticalRotationMatrix)
    eye.transformBy(horizontalRotationMatrix)

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


def newUpFromRotatingHorizontal(
    cam: Camera, horizontalRotationMatrix: Matrix3D
) -> Vector3D:
    """
    Apply the horizontal rotation matrix to the previous upVector
    """
    newUp = cam.upVector.copy()
    newUp.transformBy(horizontalRotationMatrix)
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


# Given a camera, this determines in which of the primary axis
# directions, the up vector is closest to and return that vector.
def getConstrainedUpVector(camera: Camera) -> Vector3D:
    # Determine which of the primary directions the current up vector is closest to.
    upVector = Vector3D.create(1, 0, 0)
    angle = upVector.angleTo(camera.upVector)
    if Vector3D.create(-1, 0, 0).angleTo(camera.upVector) < angle:
        upVector = Vector3D.create(-1, 0, 0)
        angle = upVector.angleTo(camera.upVector)

    if Vector3D.create(0, 1, 0).angleTo(camera.upVector) < angle:
        upVector = Vector3D.create(0, 1, 0)
        angle = upVector.angleTo(camera.upVector)

    if Vector3D.create(0, -1, 0).angleTo(camera.upVector) < angle:
        upVector = Vector3D.create(0, -1, 0)
        angle = upVector.angleTo(camera.upVector)

    if Vector3D.create(0, 0, 1).angleTo(camera.upVector) < angle:
        upVector = Vector3D.create(0, 0, 1)
        angle = upVector.angleTo(camera.upVector)

    if Vector3D.create(0, 0, -1).angleTo(camera.upVector) < angle:
        upVector = Vector3D.create(0, 0, -1)
        angle = upVector.angleTo(camera.upVector)

    return upVector


def setCam(cam: Camera):
    """
    Set the activeViewport to the given cam, makes sure to let F360 do it's work to update the view

    Args:
        cam (Camer): camera to set the viewport to
    """
    app.activeViewport.camera = cam
    doEvents()
    app.activeViewport.refresh()
