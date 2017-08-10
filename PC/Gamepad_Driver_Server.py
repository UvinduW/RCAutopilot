# Programmed by Uvindu J Wijesinghe (2017)
import socket
import netifaces as ni
import pygame
from threading import Thread
from numpy import array
import cv2
from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
import io
import struct
from time import sleep
import time
import model
import tensorflow as tf
import scipy.misc
import sys

# Gamepad Key Mapping:
# Start - Toggle between manual and autonomous mode
# Right trigger - Forwards throttle
# Left trigger - Reverse throttle
# Left thumbstick - Steering input (needs to be centered properly for autonomous mode to activate)
# A - Toggle capturing images to disk
# B - Quits the script
# X - Decrement speed of car when in autonomous mode
# Y - Increment speed of car when in autonomous mode
#
# Note: If car is in autonomous mode, it will revert to manual mode if gamepad
#       is also giving driving commands. It will revert back to autonomous
#       mode once the gamepad input stops.


# User configurable options
# Display related:
disable_display_thread = 0      # Set to 1 to disable display thread - includes sign recognition and steering wheel
disable_camera_display = 0      # Set to 1 to disable camera output on screen
disable_steering_display = 0    # Set to 1 to disable animated steering wheel display
display_scale = 2               # Scale factor for displayed image. Set to 1 for original size.

# Object recognition options:
disable_sign_recognition = 0    # Set to 1 to disable all sign recognition (overides settings below)
disable_stop_sign = 0           # Set to 1 to disable stop sign recognition
disable_traffic_light = 1       # Set to 1 to disable traffic light recognition
disable_fuel_sign = 1           # Set to 1 to disable fuel sign recognition
disable_no_entry_sign = 1       # Set to 1 to disable No Entry sign recognition
disable_car_stopping = 0        # Don't stop the car even if a stop sign or traffic light is detected
stop_activate_width = 50        # Width of the stop sign detected above which the car should stop - bigger = closer
traffic_activate_height = 90    # Height of the traffic light detected above which the car should stop - bigger = closer
print_stop_sign_width = 1       # Set to 1 to print the width of detected stop sign in terminal
print_traffic_light_height = 0  # Set to 1 to print the height of detected traffic light red light in terminal

# Start conditions:
autonomous_enabled = 1          # Set to 1 to start in autonomous mode
pause_capture = 1               # Set to 1 to start with image capturing paused
set_speed = 0                   # Initial speed for autonomous mode

# Image capturing options:
disable_capture = 0             # Images aren't captured even if button on gamepad is pressed to unpause capture
image_num = 0                   # Starting number for captured image file name

# Other options:
speed_change_step = 10          # How much to change the vehicle speed by when X or Y are pressed - for autonomous mode
transmission_interval = 0.00    # How long to wait between commands transmitted (in seconds) - if buffer fills too fast


# Continuously read the state of relevant axes on the gamepad - Thread 2
def get_input():
    global message
    global drive_values
    global send_commands

    # Throttle and brake fix variables
    throttle_pressed = 0
    reverse_pressed = 0

    # Map axes
    left_thumb_x = 0
    # LTHUMBY = 1 - not used
    left_trigger = 2
    # RTHUMBX = 3 - not used
    # RTHUMBY = 4 - not used
    right_trigger = 5

    # Get gamepad input while script is still sending commands to car
    while send_commands == 1:
        # Update gamepad conditions
        pygame.event.pump()

        # Get inputs from appropriate axes
        turn_angle = gamepad.get_axis(left_thumb_x)
        throttle = gamepad.get_axis(right_trigger)
        reverse_throtle = gamepad.get_axis(left_trigger)

        # gamepad doesn't initialises triggers to 0 until they are pressed for first time.
        # this behaviour is fixed to ensure correct inputs are obtained

        # Throttle fix
        if throttle_pressed == 0:
            if throttle == 0 or throttle == -1:
                throttle = -1.0
            else:
                throttle_pressed = 1

        # Reverse fix
        if reverse_pressed == 0:
            if reverse_throtle == 0 or reverse_throtle == -1:
                reverse_throtle = -1.0
            else:
                reverse_pressed = 1

        # Scale to 255
        throttle = int((throttle+1)*127.5)
        reverse_throtle = int((reverse_throtle+1)*127.5)
        turn_angle = int(turn_angle*255)

        # Check reverse
        if reverse_throtle > 0:
            throttle = reverse_throtle
            reverse = "1"
        else:
            reverse = "0"

        # Split left and right direction
        if turn_angle < 0:
            # Left turn
            direction = "1"
            turn_angle *= -1
        else:
            # Right turn
            direction = "0"

        # Set dead zones
        if turn_angle < 16:
            turn_angle = 0

        # Prepare strings - Note: this can also be implemented with turn_angle.zfill(3) in one line
        # Turn angle
        if turn_angle == 0:
            turn_angle = "000"
        elif turn_angle < 10:
            turn_angle = "00" + str(turn_angle)
        elif turn_angle < 100:
            turn_angle = "0" + str(turn_angle)
        else:
            turn_angle = str(turn_angle)

        # Throttle
        if throttle == 0:
            throttle = "000"
        elif throttle < 10:
            throttle = "00" + str(throttle)
        elif throttle < 100:
            throttle = "0" + str(throttle)
        else:
            throttle = str(throttle)

        # Message format: direction bit, turn angle (3 digits), reverse bit, throttle value (3 digits)
        message = direction + turn_angle + reverse + throttle
        drive_values = [direction, turn_angle, reverse, throttle]
        sleep(0.1)

    # Set message to stop car if thread is to be terminated
    message = "00000000"


# Load a frame from the client Raspberry Pi to process
def load_image(video_client):

    len_stream_image = 0
    stream_image = 0

    # Repeat until a valid image has been received from the client (ie no errors)
    while len_stream_image != 230400:
        # Read the length of the image as a 32-bit unsigned int. If the
        # length is zero, quit the loop
        image_len = struct.unpack('<L', video_client.read(struct.calcsize('<L')))[0]
        if not image_len:
            print "Break as image length is null"
            return 0
        # Construct a stream to hold the image data and read the image
        # data from the connection
        image_stream = io.BytesIO()
        image_stream.write(video_client.read(image_len))
        # Rewind the stream, open it as an image with PIL
        image_stream.seek(0)
        stream_image = Image.open(image_stream)
        # Convert image to numpy array
        stream_image = array(stream_image)

        # Check to see if full image has been loaded - this prevents errors due to images lost over network
        len_stream_image = stream_image.size
        if len_stream_image != 230400:
            # The full 320x240 image has not been received
            print "Image acquisition error. Retrying..."

    # Convert to RGB from BRG
    stream_image = stream_image[:, :, ::-1]

    return stream_image


# Set up the command and video server to allow car client to connect
def setup_servers():

    # Set up command server and wait for a connect
    print 'Waiting for Command Client'
    command_server_soc = socket.socket()  # Create a socket object
    command_server_soc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    command_server_soc.bind((host, port))  # Bind to the port

    command_server_soc.listen(0)  # Wait for client connection
    # Wait for client to connect
    command_client, addr = command_server_soc.accept()

    print "Command client connected!"

    # Once command server is connected, set up video server and wait for a connect
    print 'Waiting for Video Stream'

    # Create socket
    video_server_soc = socket.socket()
    video_server_soc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    video_server_soc.bind((host, port + 1))
    video_server_soc.listen(0)

    # Accept a single connection and make a file-like object out of it
    video_client = video_server_soc.accept()[0].makefile('rb')
    print "Video client connected!"

    # Return clients
    return command_client, video_client


# Use Haar Cascades to detect objects in image
def object_detection(cascade_classifier, gray_image, colour_image, sign_type):
    global stop_activate_width
    global traffic_activate_height
    global print_stop_sign_width
    global print_traffic_light_height

    threshold = 150     # Thresholding for traffic lights
    stop_state = 0      # Should the car be stopped

    # Run classifier on image
    cascade_obj = cascade_classifier.detectMultiScale(
        gray_image,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(30, 30),
        flags=cv2.cv.CV_HAAR_SCALE_IMAGE
    )

    # For each object found, draw rectangle around and label it
    for (x_pos, y_pos, width, height) in cascade_obj:
        # Draw rectangle around object
        cv2.rectangle(colour_image, (x_pos + 5, y_pos + 5), (x_pos + width - 5, y_pos + height - 5), (255, 255, 255), 2)

        # If it is a stop sign height and width should be the same as classifier is a square
        if width / height == 1:
            cv2.putText(colour_image, 'STOP', (x_pos, y_pos - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            if print_stop_sign_width == 1:
                print "Stop sign width: " + str(width)
            if width > stop_activate_width:
                # If sign is close, then car should be stopped - width used to indicate distance
                stop_state = 1
            else:
                stop_state = 0

        # If it is a Fuel sign
        elif sign_type == "F":
            cv2.putText(colour_image, 'Fuel', (x_pos, y_pos - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # If it is a No Entry sign
        elif sign_type == "N":
            cv2.putText(colour_image, 'No Entry', (x_pos, y_pos - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # If it is a traffic light
        else:
            stop_state = 0
            roi = gray_image[y_pos + 10:y_pos + height - 10, x_pos + 10:x_pos + width - 10]
            mask = cv2.GaussianBlur(roi, (25, 25), 0)
            (minVal, maxVal, minLoc, maxLoc) = cv2.minMaxLoc(mask)

            # check if light is on
            if maxVal - minVal > threshold:
                cv2.circle(roi, maxLoc, 5, (255, 0, 0), 2)

                # Red light
                if 1.0 / 8 * (height - 30) < maxLoc[1] < 4.0 / 8 * (height - 30):
                    cv2.putText(colour_image, 'Red', (x_pos + 5, y_pos - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255),
                                2)
                    if print_traffic_light_height == 1:
                        print "Red light height: " + str(height)
                    if height > traffic_activate_height:
                        # If traffic light is close, then car should be stopped - height used to indicate distance
                        stop_state = 1
                    else:
                        stop_state = 0

                # Green light
                elif 5.5 / 8 * (height - 30) < maxLoc[1] < height - 30:
                    cv2.putText(colour_image, 'Green', (x_pos + 5, y_pos - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255,
                                                                                                                0), 2)
                    # Car shouldn't be stopped if it's a green light
                    stop_state = 0

    # Return image and whether car should be stopped
    return colour_image, stop_state


# Display image stream to the user with information overlayed on top as well as steering animation - Thread 3
def show_image():
    global control_message
    global display_scale
    global pause_capture
    global manual_control
    global image
    global send_commands
    global smoothed_angle
    global stop_condition
    global disable_sign_recognition
    global disable_camera_display
    global disable_steering_display
    global disable_stop_sign
    global disable_traffic_light
    global disable_fuel_sign
    global disable_no_entry_sign
    global disable_car_stopping

    # Load classifiers
    stop_cascade = cv2.CascadeClassifier('cascade_xml/stop_sign.xml')
    light_cascade = cv2.CascadeClassifier('cascade_xml/traffic_light.xml')
    fuel_cascade = cv2.CascadeClassifier('cascade_xml/fuel.xml')
    no_entry_cascade = cv2.CascadeClassifier('cascade_xml/no-entry.xml')

    while send_commands == 1:

        # Object detection
        if disable_sign_recognition == 0:

            # Initialise found variables
            found_red_light = 0
            found_stop_sign = 0

            # Image should be in array format for drawing in detected objects
            colour_image = array(image)

            # Convert to Image format to convert to grayscale
            draw_image = Image.fromarray(image)

            # Convert back to array after getting grayscale for object detection
            gray_image = array(draw_image.convert('L'))

            # Detect objects and get returned image
            if disable_stop_sign == 0:
                colour_image, found_stop_sign = object_detection(stop_cascade, gray_image, colour_image, "S")
            if disable_traffic_light == 0:
                colour_image, found_red_light = object_detection(light_cascade, gray_image, colour_image, "T")
            if disable_fuel_sign == 0:
                colour_image, found_red_light = object_detection(fuel_cascade, gray_image, colour_image, "F")
            if disable_no_entry_sign == 0:
                colour_image, found_red_light = object_detection(no_entry_cascade, gray_image, colour_image, "N")

            # Check if car should be stopped
            if disable_car_stopping == 0 and (found_red_light == 1 or found_stop_sign == 1):
                stop_condition = 1
            else:
                stop_condition = 0

            # Convert object detected image back into PIL image format
            draw_image = Image.fromarray(colour_image)

        else:
            # Convert image back into PIL image format
            draw_image = Image.fromarray(image)

        # Note: colours are in BGR format for PIL text
        # Set up capturing status text
        if pause_capture == 1:
            pause_text = "Capturing Paused"
            pause_colour = (0, 255, 0)  # Green
        else:
            pause_text = "Caputuring Frames"
            pause_colour = (0, 140, 255)  # Orange

        # Set up control mode text
        if manual_control == 1:
            control_text = "   Manual Control"
            control_colour = (255, 140, 0)  # Light Blue
        else:
            control_text = "Autonomous Mode"
            control_colour = (0, 0, 255)  # Red

        # Set up steering input text and steering wheel angle
        current_angle = int(control_message[1:4])
        angle = str(current_angle * 100 / 255)
        current_angle = current_angle * 180 / 255
        if control_message[0] == "1":
            angle = "-" + str(angle)
            angle_colour = (154, 250, 0)  # Medium Spring Green
            current_angle *= -1
        else:
            angle = "+"+str(angle)
            angle_colour = (170, 178, 32)  # Light Sea Green
        angle_text = "Steering input: " + angle + "%"

        # Set up throttle input text
        throttle = str(int(control_message[5:8])*100/255)
        throttle_text = "Throttle: " + throttle + "%"  # Coral
        throttle_colour = (80, 127, 255)

        # Scale image by user specified scale factor
        basewidth = 320 * display_scale
        wpercent = (basewidth / float(draw_image.size[0]))
        hsize = int((float(draw_image.size[1]) * float(wpercent)))
        draw_image = draw_image.resize((basewidth, hsize), Image.ANTIALIAS)

        # Set up image to allow drawing on it
        draw = ImageDraw.Draw(draw_image)

        # Set font for text displayed on screen (font file should be in same directory as script)
        font = ImageFont.truetype("DejaVuSans.ttf", 15 * display_scale)

        # Draw text on screen. Scale text displayed by the scale factor
        draw.text((5 * display_scale, 10 * display_scale), angle_text, angle_colour, font=font)
        draw.text((205 * display_scale, 10 * display_scale), throttle_text, throttle_colour, font=font)
        draw.text((5 * display_scale, 220 * display_scale), pause_text, pause_colour, font=font)
        draw.text((155 * display_scale, 220 * display_scale), str("|"), (255, 255, 255), font=font)
        draw.text((170 * display_scale, 220 * display_scale), control_text, control_colour, font=font)

        # Convert back to array for display
        show_im = array(draw_image)

        # Rotate steering wheel image
        # make smooth angle transitions by turning the steering wheel based on the difference of the current angle
        # and the predicted angle
        smoothed_angle += 0.2 * pow(abs((current_angle - smoothed_angle)), 2.0 / 3.0) * (
            current_angle - smoothed_angle) / abs(current_angle - smoothed_angle)

        # Rotate steering wheel image by the smoothed angle
        rot_matrix = cv2.getRotationMatrix2D((wheel_cols / 2, wheel_rows / 2), -smoothed_angle, 1)
        dst = cv2.warpAffine(wheel, rot_matrix, (wheel_cols, wheel_rows))

        # Show image
        if disable_steering_display == 0:
            cv2.imshow("steering wheel", dst)
        if disable_camera_display == 0:
            cv2.imshow("Car View", show_im)

        cv2.waitKey(1)


# Get the turn angle from the convoluted neural network
def get_angle(full_image):
    global smoothed_angle
    global sess
    global saver

    # Resize image and normalise
    feed_image = scipy.misc.imresize(full_image[-150:], [66, 200]) / 255.0

    # Feed image into CNN to obtain the turn angle
    degrees = model.y.eval(session=sess, feed_dict={model.x: [feed_image], model.keep_prob: 1.0})[0][
                  0] * 180.0 / scipy.pi

    # print("Predicted steering angle: " + str(degrees) + " degrees")

    # Determine whether to turn left or right
    if degrees < 0:
        direction = "1"
    else:
        direction = "0"

    # Scale and convert angle to string. Note: Working trial upstairs in F2 was without scaling
    str_angle = str(int(abs(degrees*255/180)))

    # Pad string with zeros to ensure length is 3
    str_angle = str_angle.zfill(3)

    # Set up command string including the speed set for the car in autonomous mode
    ret_command = direction + str_angle + "0" + str(set_speed).zfill(3)

    # Return command string to be sent to car
    return ret_command


# Thread to receive video feed - Thread 1
def video_stream():
    global message
    global drive_values
    global send_commands
    global control_message
    global set_speed
    global autonomous_enabled
    global pause_capture
    global image_num
    global disable_capture
    global speed_change_step
    global transmission_interval
    global pause_capture
    global manual_control
    global image
    global stop_condition

    terminate_program = 0  # Flag to indicate script should be stopped
    total_frame = 0        # Count of total number of frames processed - used for frame rates
    last_send_time = 0     # Time since previous command was sent - used to control transmission rate
    show_started = 0       # Flag to indicate whether the show_images thread has started

    # Setup servers
    command_client, video_client = setup_servers()

    # Start getting control inputs from gamepad (Thread 2)
    Thread(target=get_input).start()

    print ""
    print "Press A to start collecting data"

    # Initialise start time
    start_time = time.time()

    # Start receiving images
    try:
        while send_commands == 1:
            try:
                # Load image from stream
                image_time = time.time()
                image = load_image(video_client)
                image_time = int(1000 * (time.time() - image_time))

                if len(image) == 0:
                    break

                # Count of images processed
                total_frame += 1

                # #######################-Capture Frames-########################## #
                if gamepad.get_button(0) == 1:
                    # Pause capturing data if "A" is pressed on gamepad
                    pause_capture = 1 - pause_capture
                    if pause_capture == 1:
                        # Send a stop signal to the car, to be safe
                        command_client.send("00000000")
                        print "Data capture paused"
                    else:
                        print "Data capture resumed"

                    # Delay to prevent double press being detected
                    sleep(0.5)

                # Write images to file if capturing is not paused or disabled
                if pause_capture == 0 and disable_capture == 0:
                    cv2.imwrite('training_images/frame{:>010}_command-{}.jpg'.format(image_num, message), image)
                    image_num += 1

                # ##########################-Control Car-########################### #

                # Check if speed change requested for autonomous driving
                if gamepad.get_button(3) == 1:
                    # Increment speed if "Y" is pressed on gamepad
                    set_speed += speed_change_step
                    if set_speed > 255:
                        set_speed = 255
                    # Debounce button
                    sleep(0.2)

                if gamepad.get_button(2) == 1:
                    # Decrement speed if "X" is pressed on gamepad
                    set_speed -= speed_change_step
                    if set_speed < 0:
                        set_speed = 0
                    # Debounce button
                    sleep(0.2)

                if gamepad.get_button(7) == 1:
                    # Toggle autonomous mode if "Start" is pressed on gamepad
                    autonomous_enabled = 1 - autonomous_enabled
                    # Debounce button
                    sleep(0.2)

                # Get control message
                if message == "00000000" and autonomous_enabled == 1:
                    # Only use neural network if there is no gamepad input and
                    # autonomous mode is enabled

                    manual_control = 0
                    neural_time = time.time()
                    control_message = get_angle(image)
                    neural_time = int(1000 * (time.time() - neural_time))
                    # control_message = "00000000"  # Overide autonomous mode instructions - for debugging
                else:
                    # Controller takes priority if there is input
                    manual_control = 1
                    control_message = message
                    neural_time = 0

                # Start thread to show images (Thread 3)
                if show_started == 0 and disable_display_thread == 0:
                    Thread(target=show_image).start()
                    show_started = 1

                # Stop the car if a stop sign or traffic light has triggered the stop condition due to proximity
                if stop_condition == 1:
                    control_message = "00000000"

                # Send commands to car no quicker than the specified transmission interval
                time_interval = time.time() - last_send_time
                if time_interval < transmission_interval:
                    wait_time = transmission_interval - time_interval
                    sleep(wait_time)

                command_client.send(control_message)
                time_interval = int(1000 * (time.time() - last_send_time))
                time_elapsed = int(time.time() - start_time)
                print "Time: " + str(time_elapsed).zfill(
                    4) + " | Sending command: " + control_message + " | Transmission interval: " + str(
                    time_interval).zfill(3) + " ms" + " | Image Acquisition: " + str(image_time).zfill(
                    3) + " ms" + " | Neural Network: " + str(neural_time).zfill(2) + " ms" + " | Frame rate: " + str(
                    1000 / time_interval) + " fps"
                last_send_time = time.time()

                # Stop if "B" is pressed on gamepad
                if gamepad.get_button(1) == 1:
                    command_client.send("00000000")
                    cv2.destroyAllWindows()
                    send_commands = 0

            # Error handling
            except:
                end_time = time.time()
                print ""
                print "Lost connection to video client"

                # Stop the car
                try:
                    print ""
                    print "Attempting to stop the car!"
                    send_direction = "0"
                    command_client.send(send_direction)
                    print "Car should be stopped!"
                    print ""
                except:
                    print ""
                    print "COULD NOT STOP THE CAR! Catch it if it's still in motion"

                print 'Total frame:', total_frame
                print 'Time elapsed: ', end_time - start_time
                print 'Frames per second: ', total_frame / (end_time - start_time)
                print ""

                print "Initialising video server for a reconnect..."
                # close socket
                video_client.close()

                # TODO: This will currently break - need to get this object returned from setup_servers() function
                video_server_soc.close()

                # Recreate socket objects
                video_server_soc = socket.socket()
                video_server_soc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                # Connect socket
                video_server_soc.bind((host, port + 1))

                # Listen for incoming connections for 10 seconds
                video_server_soc.settimeout(10)
                video_server_soc.listen(0)
                print "Waiting for video client to reconnect"

                # Terminate program if client doesn't connect
                try:
                    video_client = video_server_soc.accept()[0].makefile('rb')
                except:
                    print "Client didn't connect in 10 seconds. "
                    retry = raw_input("Do you want to keep waiting for a further 10 seconds? (y/n) ")
                    if retry == "y":
                        try:
                            video_client = video_server_soc.accept()[0].makefile('rb')
                        except:
                            print "Client did not connect. Program will terminate"
                            terminate_program = 1
                        # break
                        else:
                            print "Connection to video client re-established"
                    else:
                        print "Client did not connect. Program will terminate"
                        terminate_program = 1

                if terminate_program == 1:
                    sys.exit()
                else:
                    print ""

        end_time = time.time()
        print 'Total frame:', total_frame
        print 'Time elapsed: ', end_time - start_time
        print 'Frames per second: ', total_frame / (end_time - start_time)

    finally:
        # Close sockets
        if terminate_program == 1:
            video_client.close()
            video_server_soc.close()


# Initiation
print "Data Collection Server Script Initiated"

# Find interface names using ifconfig (left hand column)
# On my computer:
# Ethernet adapter was named "enp4s0"
# Wireless adapter was named "wlp3s0"

# Get PC IP Address
ni.ifaddresses('wlp3s0')
wifi = ni.ifaddresses('wlp3s0')[2][0]['addr']
ethernet = ni.ifaddresses('enp4s0')[2][0]['addr']

# Open port range on all network interfaces
host = "0.0.0.0"
port = 8000

# Set up XBox controller
pygame.init()
pygame.joystick.init()
gamepad = pygame.joystick.Joystick(0)
gamepad.init()

# Initialise variables
message = "00000000"
control_message = "00000000"
drive_values = [0, 0, 0, 0]
send_commands = 1
smoothed_angle = 1
wheel = cv2.imread('steering_wheel_image.jpg', 0)
wheel_rows, wheel_cols = wheel.shape
manual_control = 0
image = 0
stop_condition = 0

# Set up TensorFLow
sess = tf.InteractiveSession()
saver = tf.train.Saver()
saver.restore(sess, "save/model.ckpt")

# Indicate script initiation and print server details
print ""
print "Server details:"
print "WiFi - ", wifi
print "Ethernet - ", ethernet
print "Command Port - ", port
print "Video Port - ", port + 1
print ""

# Start thread (Thread 1)
Thread(target=video_stream).start()
