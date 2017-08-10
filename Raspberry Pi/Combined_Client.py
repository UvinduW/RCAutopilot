import threading
from threading import Thread
import io
import socket
import struct
import time
import picamera
import serial
from time import sleep

#host = "192.168.13.84"
#host = "192.168.0.17"
host = "192.168.0.100"
port = 8000


def steer():
    global command_client
    global ArduinoPort
    
    send_inst = True
    try:
        while send_inst:
            sleep(0.1)
            recvCommand = command_client.recv(1024)
            
            
            if (recvCommand=="q" or recvCommand==""):
                command_client.close
                print 'Exit'
                send_inst = False
                ArduinoPort.write("0")
                ArduinoPort.close()            
                break;
            else:
                print (recvCommand)
                ArduinoPort.write(recvCommand.encode())
    except:
        recvCommand = "00000000"
        ArduinoPort.write(recvCommand.encode())
        print "Error! Connection lost!"

        

def VideoStream():
    global command_client
    global ArduinoPort

    arduino_connected = 0

    #print "starting thread"
    # Set up command client
    while arduino_connected == 0:
        try:
            ArduinoPort = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
            arduino_connected = 1
        except:
            arduino_connected = 0
            print "Please check USB connection to Arduino"
            print ""
            print "Retrying Arduino connection..."
            # Wait 2 seconds before retrying connection
            sleep(2)

    #Initialise everything
    print "Connecting to command server"
    command_client = socket.socket()	#Create a socket object
    command_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    command_client.connect((host, port))	#Bind to the port
    print  "Should be connected to command server"
    print ""

    #Start thread to handle control requests
    Thread(target = steer).start()

    # Wait 0.5 seconds to allow video server to initialise
    sleep(0.5)
    
    # Set up video client
    print "Connecting to video server"
    video_socket = socket.socket()
    video_socket.connect((host, port+1))

    # Make a file-like object out of the connection
    connection = video_socket.makefile('wb')
    print  "Should be connected to video server"
    print ""
    try:
        camera = picamera.PiCamera()
        camera.resolution = (320, 240)
        #Set to true if camera is flipped vertically
        camera.vflip = True
        camera.hflip = True
        # Start a preview and let the camera warm up for 2 seconds
        #camera.start_preview()
        time.sleep(2)

        # Note the start time and construct a stream to hold image data
        # temporarily (we could write it directly to connection but in this
        # case we want to find out the size of each capture first to keep
        # our protocol simple)
        start = time.time()
        stream = io.BytesIO()
        for foo in camera.capture_continuous(stream, 'jpeg',use_video_port = True):
            # Write the length of the capture to the stream and flush to
            # ensure it actually gets sent
            connection.write(struct.pack('<L', stream.tell()))
            connection.flush()
            # Rewind the stream and send the image data over the wire
            stream.seek(0)
            connection.write(stream.read())
            # If we've been capturing for more than 30 seconds, quit
            #if time.time() - start > 30:
            #    break
            # Reset the stream for the next capture
            stream.seek(0)
            stream.truncate()
        # Write a length of zero to the stream to signal we're done
        connection.write(struct.pack('<L', 0))
    finally:
        recvCommand = "00000000"
        ArduinoPort.write(recvCommand.encode())
        print "Error! Connection lost!"
        connection.close()
        video_socket.close()    

#Start threads
Thread(target = VideoStream).start()


