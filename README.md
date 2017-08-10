# RCAutopilot
__Note: This repository is still in progress__
## Overview
This is a small scale demonstration of how a self-driving system could be implemented using a toy radio controlled car. This project has been implemented mainly in Python with a bit of C/C++ needed for the Arduino.
### How it works
__Training__

Before the car can be run in autonomous mode, it needs to be manually trained (my trained model is included). Video is captured by the Raspberry Pi using the Camera Module which is mounted on top of the car. This video is streamed over the wifi network to the PC. A gamepad connected to the PC is used to manually control the car. Each frame of video received is stored on the PC, along with the corresponding user input (steering input and throttle input). The user has to manually drive the car around the track numerous times to collect sufficient training data and cover the different conditions that the car may encounter.
Once the training is complete, a script needs to be run to train the model. Depending on the number of images and the processing power of the PC, the training process can take a few hours. Once the training is complete, a file is produced containing the trained model.

__Driving__

Once the trained model has been obtained, the car can be run in autonomous mode. Once the car is set to autonomous mode and a desired speed is selected, the PC takes the input image streaned from the Raspberry Pi, processes it using a convoluted neural network, and generates an appropriate steering angle. This steering angle is then sent back to the Raspberry Pi over wifi. An Arduino is connected to the Raspberry Pi over USB, and this steering angle is sent to the Arduino. The Arduino is connected to the ESC and provides the appropriate PWM signal to it, ensuring the car turns by the required amount.

## Components
These are the components I used to make this project. These aren't set in stone, and can be substituted for other parts that may do a similar or even better job
- Raspberry Pi
- Rapberry Pi Camera Module
- Portable Power Bank
- Arduino
- Modified Tamiya Ford Focus RS WRC 02 Chassis
  - TL-01 Chassis
  - TBLE-02S Electronic Speed Control (ESC)
  - 7.2V 3000 mAh NiMH battery
- PC with Ubuntu
- TP-Link TL-WR702N Nano Router (optional)
- Xbox One controller (code can be altered to work with other controllers if they can be recognised on Ubuntu)


Todo:
- Add files
- Explain how to use the scripts
