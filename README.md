# Joystick Control for Fusion 360

An add-in for Fusion 360 that allows you to use joysticks (and other gamepad controls) to control the active viewport.

# Usage

Set up with controls that make sense to me (using an XBox360 controller):
 - Left joystick controls panning up/down/left/right
 - Right joystick controls rotating up/down/left/right (NOTE: I'm not happy with how vertical rotation works, happy to accept a pull request that would make it operate like the "constrained orbit" control, it current operates like the "free move" control)
 - Triggers control zoom (NOTE: a bit buggy the first time you use a trigger to zoom, probably something with my view extent math)
 - D-pad (hat) moves to specific view:
   - Up: top
   - Down: bottom
   - Left: left
   - Right: right
 - Buttons also do views:
   - B: front
   - A: back
   - X: home
  
If you don't like this setup, you should be able to configure it by updating the variables at the beginning.

My joysticks seem to sit around .1 when resting, so I made the deadzone .15.

I've set up what I think is a comfortable curve for the panning axes: f((x*10)^3/10): ![image](https://github.com/user-attachments/assets/0fcb9818-7a36-49ad-83e3-5b76f7aa17c7)

This can be configured by editing `scalePanAxis` method.

# Implementation notes

Given Fusion 360's weird setup for using libraries, I found it easier to use some simpler libraries, and found [pyjoystick](https://github.com/justengel/pyjoystick). It took some slight modification to get it working using local references to other libraries. I'm not sure how the `import pygame` in there works, but it seems to work on my local machine. Fusion 360 supposedly operates in a 64 bit architecture container, and I've tested that the sdl dll lookup for windows works. I don't know if it works for mac.

The libraries were installed using pip in a local folder and then copied up to the `Modules` folder.

The add-in is marked as supporting mac, but I haven't tried it there.
